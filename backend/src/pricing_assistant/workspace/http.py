"""Workspace query API: queue, summary cards, item detail, match queue, review sessions (11.x)."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict

from pricing_assistant.catalog.api import ImportanceTier
from pricing_assistant.collection.api import EvidenceStore, Freshness, presigned_url
from pricing_assistant.core.deps import DatabaseDep
from pricing_assistant.core.errors import NotFound
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.decisions.api import DecisionView
from pricing_assistant.iam.api import ExpertPrincipal, Role
from pricing_assistant.pricing.api import Outcome
from pricing_assistant.workspace import detail as detail_view
from pricing_assistant.workspace import matches as match_view
from pricing_assistant.workspace import queue as queue_view
from pricing_assistant.workspace import sessions

router = APIRouter(route_class=IdempotentRoute, tags=["workspace"])
PUBLIC_ATTRIBUTES = (
    "capacity",
    "generation",
    "frequency",
    "colour_edition",
    "warranty_provider",
    "warranty_months",
)


class ScoreOut(BaseModel):
    score: int
    tier_multiplier: int
    outcome_weight: int
    profit_impact_rial: int
    profit_points: int
    open_since: datetime
    age_hours: int
    age_points: int


class QueueItemOut(BaseModel):
    variant_id: uuid.UUID
    sku: str
    product_name: str
    brand: str
    model: str
    category: str
    tier: ImportanceTier
    attributes: dict[str, Any]
    recommendation_id: uuid.UUID
    outcome: Outcome
    reason_code: str
    flags: list[str]
    our_price_rial: int | None
    market_ref_rial: int | None
    market_label: Literal["stale", "failed"] | None
    suggested_price_rial: int | None
    floor_rial: int | None
    ceiling_rial: int | None
    evaluated_at: datetime
    status: queue_view.QueueStatus
    decision_id: uuid.UUID | None
    alerts: list[queue_view.Alert]
    score: ScoreOut


class QueuePageOut(BaseModel):
    items: list[QueueItemOut]
    total: int
    next_cursor: str | None


class CardOut(BaseModel):
    key: str
    title_fa: str
    count: int
    primary: bool
    target: Literal["queue", "matches"]
    filter: dict[str, Any]  # the queue query parameters that list exactly these items


def _item_out(item: queue_view.QueueItem) -> QueueItemOut:
    rec, variant, score = item.recommendation, item.variant, item.score
    return QueueItemOut(
        variant_id=variant.id,
        sku=variant.sku,
        product_name=variant.product_name,
        brand=variant.brand,
        model=variant.model,
        category=variant.category,
        tier=variant.importance_tier,
        attributes={k: variant.attributes[k] for k in PUBLIC_ATTRIBUTES if k in variant.attributes},
        recommendation_id=rec.id,
        outcome=Outcome(rec.outcome),
        reason_code=rec.reason_code,
        flags=list(rec.flags),
        our_price_rial=rec.our_price_rial,
        market_ref_rial=rec.market_ref_rial,
        market_label=item.market_label,  # type: ignore[arg-type]
        suggested_price_rial=rec.suggested_price_rial,
        floor_rial=rec.floor_rial,
        ceiling_rial=rec.ceiling_rial,
        evaluated_at=rec.evaluated_at,
        status=item.status,
        decision_id=item.decision_id,
        alerts=list(item.alerts),
        score=ScoreOut(
            score=score.score,
            tier_multiplier=score.tier_multiplier,
            outcome_weight=score.outcome_weight,
            profit_impact_rial=score.profit_impact_rial,
            profit_points=score.profit_points,
            open_since=score.open_since,
            age_hours=score.age_hours,
            age_points=score.age_points,
        ),
    )


def _filter_params(flt: queue_view.QueueFilter) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for name, values in (
        ("category", flt.categories),
        ("tier", flt.tiers),
        ("outcome", flt.outcomes),
        ("status", flt.statuses),
    ):
        if values:
            params[name] = sorted(str(v) for v in values)
    if flt.source_health is not None:
        params["source_health"] = flt.source_health.value
    if flt.price_position is not None:
        params["price_position"] = flt.price_position.value
    return params


@router.get("/queue", response_model=QueuePageOut)
async def list_queue(
    principal: ExpertPrincipal,
    db: DatabaseDep,
    category: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query list default
    tier: Annotated[list[ImportanceTier], Query()] = [],  # noqa: B006
    outcome: Annotated[list[Outcome], Query()] = [],  # noqa: B006
    status_: Annotated[list[queue_view.QueueStatus], Query(alias="status")] = [],  # noqa: B006
    source_health: queue_view.SourceHealthFilter | None = None,
    price_position: queue_view.PricePosition | None = None,
    limit: Annotated[int, Query(ge=1, le=queue_view.MAX_PAGE)] = queue_view.DEFAULT_PAGE,
    cursor: str | None = None,
) -> QueuePageOut:
    flt = queue_view.QueueFilter(
        categories=frozenset(category),
        tiers=frozenset(tier),
        outcomes=frozenset(outcome),
        statuses=frozenset(status_),
        source_health=source_health,
        price_position=price_position,
    )
    async with db.tenant_session(principal.tenant_id) as session:
        items = await queue_view.load_queue(session)
    result = queue_view.page(items, flt, limit=limit, cursor=cursor)
    return QueuePageOut(
        items=[_item_out(i) for i in result.items],
        total=result.total,
        next_cursor=result.next_cursor,
    )


@router.get("/queue/summary", response_model=list[CardOut])
async def queue_summary(principal: ExpertPrincipal, db: DatabaseDep) -> list[CardOut]:
    """Summary cards; each count equals the length of the queue its filter opens."""
    async with db.tenant_session(principal.tenant_id) as session:
        items = await queue_view.load_queue(session)
        pending, suggested = await match_view.match_queue(session)
    cards = [
        CardOut(
            key=card.key,
            title_fa=card.title_fa,
            count=count,
            primary=card.primary,
            target="queue",
            filter=_filter_params(card.filter),
        )
        for card, count in queue_view.card_counts(items, is_admin=principal.has_role(Role.ADMIN))
    ]
    cards.insert(
        5,
        CardOut(
            key="pending_matches",
            title_fa="تطبیق‌های در انتظار تأیید",
            count=match_view.pending_count(pending, suggested),
            primary=False,
            target="matches",
            filter={},
        ),
    )
    return cards


# --- detail --------------------------------------------------------------------------------------


class EvidenceLinkOut(BaseModel):
    id: uuid.UUID
    kind: str
    url: str | None


class EvidenceRowOut(BaseModel):
    observation_id: uuid.UUID
    tracked_offer_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    url: str
    seller: str | None
    title: str | None
    price_rial: int | None
    stock_state: str
    conditions: dict[str, Any]
    observed_at: datetime
    age_seconds: int
    freshness: Freshness
    match_version_id: uuid.UUID
    match_state: str
    match_flags: list[str]
    flags: list[str]
    qualifies: bool
    is_market_reference: bool
    reasons: list[str]
    reasons_fa: list[str]
    evidence: list[EvidenceLinkOut]


class DecisionSummaryOut(BaseModel):
    id: uuid.UUID
    recommendation_id: uuid.UUID
    type: str
    status: str
    applied_price_rial: int | None
    below_floor_override: bool
    actor: str
    created_at: datetime


class ItemDetailOut(BaseModel):
    item: QueueItemOut
    explanation: str
    explanation_llm: str | None
    qualifying_count: int
    median_rial: int | None
    excluded_outlier_ids: list[uuid.UUID]
    profit_current_rial: int | None
    profit_suggested_rial: int | None
    engine_version: str
    inputs_purged: bool
    evidence: list[EvidenceRowOut]
    decision: DecisionSummaryOut | None


def _decision_out(view: DecisionView | None) -> DecisionSummaryOut | None:
    if view is None:
        return None
    d = view.decision
    return DecisionSummaryOut(
        id=d.id,
        recommendation_id=d.recommendation_id,
        type=d.type,
        status=view.status.value,
        applied_price_rial=d.applied_price_rial,
        below_floor_override=d.below_floor_override,
        actor=d.actor,
        created_at=d.created_at,
    )


@router.get("/queue/{variant_id}", response_model=ItemDetailOut)
async def queue_item(
    variant_id: uuid.UUID, request: Request, principal: ExpertPrincipal, db: DatabaseDep
) -> ItemDetailOut:
    store: EvidenceStore = request.app.state.evidence_store
    async with db.tenant_session(principal.tenant_id) as session:

        async def presign(evidence_id: uuid.UUID) -> detail_view.EvidenceLink:
            try:
                row, url = await presigned_url(session, store, evidence_id)
            except NotFound:
                return detail_view.EvidenceLink(id=evidence_id, kind="expired", url=None)
            return detail_view.EvidenceLink(id=evidence_id, kind=row.kind, url=url)

        detail = await detail_view.item_detail(session, variant_id, presign)
    rec = detail.item.recommendation
    return ItemDetailOut(
        item=_item_out(detail.item),
        explanation=rec.explanation,
        explanation_llm=rec.explanation_llm,
        qualifying_count=rec.qualifying_count,
        median_rial=rec.median_rial,
        excluded_outlier_ids=list(rec.excluded_outlier_ids),
        profit_current_rial=rec.profit_current_rial,
        profit_suggested_rial=rec.profit_suggested_rial,
        engine_version=rec.engine_version,
        inputs_purged=detail.inputs_purged,
        evidence=[
            EvidenceRowOut(
                **{
                    name: getattr(row, name)
                    for name in EvidenceRowOut.model_fields
                    if name not in {"reasons", "evidence"}
                },
                reasons=[r.value for r in row.reasons],
                evidence=[EvidenceLinkOut(id=e.id, kind=e.kind, url=e.url) for e in row.evidence],
            )
            for row in detail.rows
        ],
        decision=_decision_out(detail.decision),
    )


# --- match confirmation queue --------------------------------------------------------------------


class AttributeOut(BaseModel):
    name: str
    ours: str | int | None
    theirs: str | int | None
    source: str | None
    state: Literal["equal", "different", "missing_offer", "missing_ours"]


class VariantRefOut(BaseModel):
    id: uuid.UUID
    sku: str
    product_name: str
    brand: str
    model: str


class PendingMatchOut(BaseModel):
    match_version_id: uuid.UUID
    state: Literal["proposed", "needs_review"]
    flags: list[str]
    confidence_bp: int
    decided_by: str
    reason: str | None
    variant: VariantRefOut
    tracked_offer_id: uuid.UUID
    url: str
    source_name: str
    seller_key: str
    title: str | None
    price_rial: int | None
    observed_at: datetime | None
    attributes: list[AttributeOut]


class SuggestedOfferOut(BaseModel):
    tracked_offer_id: uuid.UUID
    url: str
    source_name: str
    variant: VariantRefOut
    suggested_by: str | None
    rationale: str | None
    created_at: datetime


class MatchQueueOut(BaseModel):
    matches: list[PendingMatchOut]
    suggested_offers: list[SuggestedOfferOut]


def _variant_ref(v: Any) -> VariantRefOut:
    return VariantRefOut(
        id=v.id, sku=v.sku, product_name=v.product_name, brand=v.brand, model=v.model
    )


@router.get("/match-queue", response_model=MatchQueueOut)
async def match_queue(principal: ExpertPrincipal, db: DatabaseDep) -> MatchQueueOut:
    async with db.tenant_session(principal.tenant_id) as session:
        pending, suggested = await match_view.match_queue(session)
    return MatchQueueOut(
        matches=[
            PendingMatchOut(
                match_version_id=p.match.id,
                state=p.match.state,  # type: ignore[arg-type]
                flags=list(p.match.flags),
                confidence_bp=p.match.confidence_bp,
                decided_by=p.match.decided_by,
                reason=p.match.reason,
                variant=_variant_ref(p.variant),
                tracked_offer_id=p.offer.id,
                url=p.offer.url,
                source_name=p.source_name,
                seller_key=p.match.seller_key,
                title=p.observation.title if p.observation else None,
                price_rial=p.observation.price_rial if p.observation else None,
                observed_at=p.observation.observed_at if p.observation else None,
                attributes=[
                    AttributeOut(
                        name=a.name,
                        ours=a.ours,
                        theirs=a.theirs,
                        source=a.source,
                        state=a.state,  # type: ignore[arg-type]
                    )
                    for a in p.attributes
                ],
            )
            for p in pending
        ],
        suggested_offers=[
            SuggestedOfferOut(
                tracked_offer_id=s.offer.id,
                url=s.offer.url,
                source_name=s.source_name,
                variant=_variant_ref(s.variant),
                suggested_by=s.offer.suggested_by,
                rationale=s.offer.suggestion_rationale,
                created_at=s.offer.created_at,
            )
            for s in suggested
        ],
    )


# --- review sessions ------------------------------------------------------------------------------


class ReviewSessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: uuid.UUID
    recommendation_id: uuid.UUID | None = None


class ReviewSessionCloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["decision", "left"]
    decision_id: uuid.UUID | None = None


class ReviewSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID
    recommendation_id: uuid.UUID | None
    opened_at: datetime
    last_activity_at: datetime
    closed_at: datetime | None
    close_reason: Literal["decision", "left", "idle"] | None
    duration_seconds: int | None


@router.post(
    "/review-sessions", status_code=status.HTTP_201_CREATED, response_model=ReviewSessionOut
)
async def open_review_session(
    body: ReviewSessionIn, principal: ExpertPrincipal, db: DatabaseDep
) -> sessions.ReviewSessionRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await sessions.open_session(
            session,
            principal=principal,
            variant_id=body.variant_id,
            recommendation_id=body.recommendation_id,
        )


@router.post("/review-sessions/{session_id}/activity", response_model=ReviewSessionOut)
async def review_session_activity(
    session_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> sessions.ReviewSessionRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await sessions.record_activity(session, principal=principal, session_id=session_id)


@router.post("/review-sessions/{session_id}/close", response_model=ReviewSessionOut)
async def close_review_session(
    session_id: uuid.UUID, body: ReviewSessionCloseIn, principal: ExpertPrincipal, db: DatabaseDep
) -> sessions.ReviewSessionRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await sessions.close_session(
            session,
            principal=principal,
            session_id=session_id,
            reason=sessions.CloseReason(body.reason),
            decision_id=body.decision_id,
        )
