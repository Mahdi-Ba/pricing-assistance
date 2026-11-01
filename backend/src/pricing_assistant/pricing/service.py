"""Recommendation orchestration: recompute, persist, supersede, replay (tasks 9.5–9.8)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.catalog.api import (
    ImportanceTier,
    ResolvedRule,
    effective_cost_from_refs,
    resolve_versions,
)
from pricing_assistant.collection.api import ObservationRow, missing_observations
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.matching.api import MatchVersionRow
from pricing_assistant.pricing.engine import (
    ENGINE_VERSION,
    Disqualification,
    OfferInput,
    RecommendationInputs,
    RecommendationResult,
    disqualifications,
    recommend,
)
from pricing_assistant.pricing.events import OutlierConfirmed, RecommendationCreated
from pricing_assistant.pricing.explain import ReferenceOffer, explain
from pricing_assistant.pricing.inputs import Gathered, condition_equivalent, gather
from pricing_assistant.pricing.models import OutlierConfirmationRow, RecommendationRow


def _offer_json(offer: OfferInput) -> dict[str, Any]:
    return {
        "observation_id": str(offer.observation_id),
        "match_version_id": str(offer.match_version_id),
        "source_approved": offer.source_approved,
    }


def _snapshot(gathered: Gathered) -> dict[str, Any]:
    """What replay cannot re-derive from immutable references (time, our price, source status)."""
    inputs = gathered.inputs
    return {
        "evaluated_at": inputs.evaluated_at.isoformat(),
        "tier": inputs.tier.value,
        "our_price_rial": inputs.our_price_rial,
        "offers": [_offer_json(o) for o in inputs.offers],
    }


async def current_recommendation(
    session: AsyncSession, variant_id: uuid.UUID, *, lock: bool = False
) -> RecommendationRow | None:
    query = select(RecommendationRow).where(
        RecommendationRow.variant_id == variant_id, RecommendationRow.superseded_by.is_(None)
    )
    if lock:
        query = query.with_for_update()
    row: RecommendationRow | None = await session.scalar(query)
    return row


async def recommendations_for_variant(
    session: AsyncSession, variant_id: uuid.UUID
) -> list[RecommendationRow]:
    """Every recommendation version of the variant, oldest first."""
    rows = await session.scalars(
        select(RecommendationRow)
        .where(RecommendationRow.variant_id == variant_id)
        .order_by(RecommendationRow.created_at, RecommendationRow.id)
    )
    return list(rows.all())


def _same(row: RecommendationRow, result: RecommendationResult, gathered: Gathered) -> bool:
    return (
        row.outcome == result.outcome.value
        and row.reason_code == result.reason.value
        and row.suggested_price_rial == result.suggested_price_rial
        and row.floor_rial == result.floor_rial
        and row.market_ref_observation_id == result.market_ref_observation_id
        and row.our_price_rial == gathered.inputs.our_price_rial
        and sorted(row.excluded_outlier_ids, key=str)
        == sorted(result.excluded_outlier_ids, key=str)
        and row.flags == [f.value for f in result.flags]
        and sorted(row.observation_ids, key=str)
        == sorted((o.observation_id for o in gathered.inputs.offers), key=str)
    )


def _explanation(
    result: RecommendationResult, gathered: Gathered, observed_at: dict[uuid.UUID, datetime]
) -> str:
    ref = None
    ref_id = result.market_ref_observation_id
    if ref_id is not None:
        offer = next(o for o in gathered.inputs.offers if o.observation_id == ref_id)
        ref = ReferenceOffer(
            seller=gathered.sellers.get(ref_id),
            source_name=gathered.sources.get(offer.source_id, ""),
            observed_at=observed_at[ref_id],
        )
    return explain(result, ref)


async def recompute(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> RecommendationRow | None:
    """Compute the variant's recommendation; store it if it differs from the current one."""
    now = now or datetime.now(UTC)
    gathered = await gather(session, variant_id, now)
    if gathered is None:
        return None
    result = recommend(gathered.inputs, gathered.rule)
    current = await current_recommendation(session, variant_id, lock=True)
    if current is not None and _same(current, result, gathered):
        return None
    row = RecommendationRow(
        id=new_id(),
        tenant_id=tenant_id,
        variant_id=variant_id,
        outcome=result.outcome.value,
        reason_code=result.reason.value,
        flags=[f.value for f in result.flags],
        suggested_price_rial=result.suggested_price_rial,
        our_price_rial=gathered.inputs.our_price_rial,
        floor_rial=result.floor_rial,
        ceiling_rial=result.ceiling_rial,
        market_ref_rial=result.market_ref_rial,
        market_ref_observation_id=result.market_ref_observation_id,
        median_rial=result.median_rial,
        qualifying_count=result.qualifying_count,
        qualifying_observation_ids=list(result.qualifying_observation_ids),
        excluded_outlier_ids=list(result.excluded_outlier_ids),
        effective_cost_rial=gathered.inputs.effective_cost_rial,
        profit_current_rial=result.profit_current_rial,
        profit_suggested_rial=result.profit_suggested_rial,
        explanation=_explanation(
            result, gathered, {o.observation_id: o.observed_at for o in gathered.inputs.offers}
        ),
        observation_ids=[o.observation_id for o in gathered.inputs.offers],
        match_version_ids=list(gathered.match_version_ids),
        outlier_confirmation_ids=list(gathered.outlier_confirmation_ids),
        cost_record_id=gathered.cost.cost_record_id if gathered.cost else None,
        cost_component_ids=list(gathered.cost.component_ids) if gathered.cost else [],
        rule_version_ids=list(gathered.rule.version_ids) if gathered.rule else [],
        inputs=_snapshot(gathered),
        evaluated_at=now,
        engine_version=ENGINE_VERSION,
    )
    if current is not None:
        current.superseded_by = row.id
        current.superseded_at = now
        await session.flush()
    session.add(row)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=RecommendationCreated(
            recommendation_id=row.id,
            variant_id=variant_id,
            outcome=row.outcome,
            superseded_id=current.id if current else None,
        ),
    )
    return row


@dataclass(frozen=True, slots=True)
class ReplayResult:
    recommendation_id: uuid.UUID
    identical: bool
    inputs_purged: bool
    stored: dict[str, Any]
    recomputed: dict[str, Any] | None


def _summary(
    outcome: str, reason: str, suggested: int | None, floor: int | None, market: int | None
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "reason_code": reason,
        "suggested_price_rial": suggested,
        "floor_rial": floor,
        "market_ref_rial": market,
    }


async def snapshot_inputs(session: AsyncSession, row: RecommendationRow) -> RecommendationInputs:
    """The engine inputs of a stored recommendation, rebuilt from its immutable references."""
    snapshot = row.inputs
    approved = {uuid.UUID(o["observation_id"]): o["source_approved"] for o in snapshot["offers"]}
    observations = {
        o.id: o
        for o in (
            await session.scalars(
                select(ObservationRow).where(ObservationRow.id.in_(row.observation_ids))
            )
        ).all()
    }
    matches = {
        m.id: m
        for m in (
            await session.scalars(
                select(MatchVersionRow).where(MatchVersionRow.id.in_(row.match_version_ids))
            )
        ).all()
    }
    confirmed = (
        set(
            (
                await session.scalars(
                    select(OutlierConfirmationRow.observation_id).where(
                        OutlierConfirmationRow.id.in_(row.outlier_confirmation_ids)
                    )
                )
            ).all()
        )
        if row.outlier_confirmation_ids
        else set()
    )
    offers = []
    for item in snapshot["offers"]:
        obs = observations[uuid.UUID(item["observation_id"])]
        match = matches[uuid.UUID(item["match_version_id"])]
        offers.append(
            OfferInput(
                observation_id=obs.id,
                source_id=obs.source_id,
                seller=obs.seller,
                price_rial=obs.price_rial,
                in_stock=obs.stock_state == "in_stock",
                valid=obs.validity == "valid",
                observed_at=obs.observed_at,
                match_version_id=match.id,
                match_confirmed=match.state == "confirmed",
                match_pending=match.state in ("proposed", "needs_review"),
                condition_equivalent=condition_equivalent(match),
                source_approved=approved[obs.id],
                outlier_confirmed=obs.id in confirmed,
            )
        )
    inputs = RecommendationInputs(
        variant_id=row.variant_id,
        tier=ImportanceTier(snapshot["tier"]),
        our_price_rial=snapshot["our_price_rial"],
        effective_cost_rial=await effective_cost_from_refs(
            session, row.cost_record_id, list(row.cost_component_ids)
        ),
        evaluated_at=datetime.fromisoformat(snapshot["evaluated_at"]),
        offers=tuple(offers),
    )
    return inputs


@dataclass(frozen=True, slots=True)
class EvidenceOffer:
    offer: OfferInput
    disqualifications: list[Disqualification]


@dataclass(frozen=True, slots=True)
class RecommendationEvidence:
    inputs: RecommendationInputs
    rule: ResolvedRule | None
    offers: list[EvidenceOffer]


async def recommendation_evidence(
    session: AsyncSession, row: RecommendationRow
) -> RecommendationEvidence | None:
    """The offers behind a stored recommendation and why each did or did not qualify.

    Evaluated as of the recommendation's time with its rule versions, so it explains the stored
    result. None when retention already purged some of its observations.
    """
    if await missing_observations(session, list(row.observation_ids)):
        return None
    inputs = await snapshot_inputs(session, row)
    rule = (
        await resolve_versions(session, list(row.rule_version_ids))
        if row.rule_version_ids
        else None
    )
    excluded = tuple(row.excluded_outlier_ids)
    return RecommendationEvidence(
        inputs=inputs,
        rule=rule,
        offers=[
            EvidenceOffer(o, disqualifications(o, inputs, rule, excluded)) for o in inputs.offers
        ],
    )


async def replay(session: AsyncSession, recommendation_id: uuid.UUID) -> ReplayResult:
    """Recompute a stored recommendation from its referenced inputs and compare (task 9.7)."""
    row = await session.get(RecommendationRow, recommendation_id)
    if row is None:
        raise NotFound("Recommendation not found", message_fa="پیشنهاد قیمت یافت نشد.")
    stored = _summary(
        row.outcome, row.reason_code, row.suggested_price_rial, row.floor_rial, row.market_ref_rial
    )
    if await missing_observations(session, list(row.observation_ids)):
        return ReplayResult(
            row.id, identical=False, inputs_purged=True, stored=stored, recomputed=None
        )
    inputs = await snapshot_inputs(session, row)
    result = recommend(inputs, await resolve_versions(session, list(row.rule_version_ids)))
    recomputed = _summary(
        result.outcome.value,
        result.reason.value,
        result.suggested_price_rial,
        result.floor_rial,
        result.market_ref_rial,
    )
    return ReplayResult(
        row.id,
        identical=recomputed == stored,
        inputs_purged=False,
        stored=stored,
        recomputed=recomputed,
    )


async def confirm_outlier(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    observation_id: uuid.UUID,
    reason: str,
) -> OutlierConfirmationRow:
    """An expert accepts a flagged low price as genuine for this observation only (task 9.8)."""
    if not reason.strip():
        raise ValidationFailed("A reason is required", message_fa="دلیل را وارد کنید.")
    observation = await session.get(ObservationRow, observation_id)
    if observation is None:
        raise NotFound("Observation not found", message_fa="مشاهده یافت نشد.")
    current = await current_recommendation(session, observation.variant_id)
    if current is None or observation_id not in current.excluded_outlier_ids:
        raise Conflict(
            "This observation is not an excluded outlier of the current recommendation",
            code="not_an_outlier",
            message_fa="این مشاهده در پیشنهاد فعلی به‌عنوان قیمت پرت کنار گذاشته نشده است.",
        )
    if await session.scalar(
        select(OutlierConfirmationRow.id).where(
            OutlierConfirmationRow.observation_id == observation_id
        )
    ):
        raise Conflict("Already confirmed", message_fa="این مشاهده قبلاً تأیید شده است.")
    confirmation = OutlierConfirmationRow(
        id=new_id(),
        tenant_id=tenant_id,
        observation_id=observation_id,
        variant_id=observation.variant_id,
        actor=actor.username,
        reason=reason,
    )
    session.add(confirmation)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=OutlierConfirmed(observation_id=observation_id, variant_id=observation.variant_id),
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="pricing.outlier.confirmed",
        target_type="observation",
        target_id=observation_id,
        after={"price_rial": observation.price_rial, "seller": observation.seller},
        reason=reason,
    )
    return confirmation
