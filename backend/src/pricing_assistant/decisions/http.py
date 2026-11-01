"""HTTP API for decisions, override reviews, outcome reports and variant history (tasks 10.2–10.8).

Amounts are integer Rial. The API records what the expert did in the store by hand; it never
changes a price anywhere.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pricing_assistant.core.deps import DatabaseDep
from pricing_assistant.core.errors import NotFound
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.decisions import history, service
from pricing_assistant.decisions.models import DecisionRow, DecisionType
from pricing_assistant.iam.api import AdminPrincipal, ExpertPrincipal, Role, actor_of

router = APIRouter(route_class=IdempotentRoute, tags=["decisions"])

Reason = Annotated[str, StringConstraints(max_length=2_000)]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: DecisionType
    reason: Reason
    applied_price_rial: Annotated[int, Field(gt=0, le=10**13)] | None = None
    override_reason: Reason | None = None
    supersedes_decision_id: uuid.UUID | None = None


class OverrideReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: Reason


class OverrideReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    verdict: Literal["approved", "rejected", "self_approved"]
    reason: str
    actor: str
    created_at: datetime


class OutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: Literal[
        "reported_done", "observed_on_site", "reflected_in_channel", "verification_overdue"
    ]
    occurred_at: datetime
    actor: str | None
    observation_id: uuid.UUID | None
    delay_seconds: int | None


class DecisionOut(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    recommendation_id: uuid.UUID
    type: DecisionType
    reason: str
    applied_price_rial: int | None
    floor_rial: int | None
    below_floor_override: bool
    override_reason: str | None
    supersedes_decision_id: uuid.UUID | None
    superseded_by: uuid.UUID | None
    actor: str
    created_at: datetime
    status: service.DecisionStatus
    override_review: OverrideReviewOut | None
    outcomes: list[OutcomeOut]


class RecommendationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    outcome: str
    reason_code: str
    suggested_price_rial: int | None
    our_price_rial: int | None
    floor_rial: int | None
    market_ref_rial: int | None
    explanation: str
    evaluated_at: datetime
    superseded_by: uuid.UUID | None


class HistoryItemOut(BaseModel):
    recommendation: RecommendationSummary
    decisions: list[DecisionOut]


def _out(view: history.DecisionView) -> DecisionOut:
    d = view.decision
    return DecisionOut(
        id=d.id,
        variant_id=d.variant_id,
        recommendation_id=d.recommendation_id,
        type=DecisionType(d.type),
        reason=d.reason,
        applied_price_rial=d.applied_price_rial,
        floor_rial=d.floor_rial,
        below_floor_override=d.below_floor_override,
        override_reason=d.override_reason,
        supersedes_decision_id=d.supersedes_decision_id,
        superseded_by=view.superseded_by,
        actor=d.actor,
        created_at=d.created_at,
        status=view.status,
        override_review=OverrideReviewOut.model_validate(view.review) if view.review else None,
        outcomes=[OutcomeOut.model_validate(o) for o in view.outcomes],
    )


async def _view(db: DatabaseDep, tenant_id: uuid.UUID, decision_id: uuid.UUID) -> DecisionOut:
    async with db.tenant_session(tenant_id) as session:
        decision = await session.get(DecisionRow, decision_id)
        if decision is None:
            raise NotFound("Decision not found", message_fa="تصمیم یافت نشد.")
        views = await history.decision_views(session, [decision])
    return _out(views[decision_id])


@router.post(
    "/recommendations/{recommendation_id}/decisions",
    status_code=status.HTTP_201_CREATED,
    response_model=DecisionOut,
)
async def record_decision(
    recommendation_id: uuid.UUID, body: DecisionIn, principal: ExpertPrincipal, db: DatabaseDep
) -> DecisionOut:
    async with db.tenant_session(principal.tenant_id) as session:
        decision = await service.record_decision(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            is_admin=principal.has_role(Role.ADMIN),
            command=service.DecisionCommand(
                recommendation_id=recommendation_id,
                type=body.type,
                reason=body.reason,
                applied_price_rial=body.applied_price_rial,
                override_reason=body.override_reason,
                supersedes_decision_id=body.supersedes_decision_id,
            ),
        )
    return await _view(db, principal.tenant_id, decision.id)


@router.get("/decisions/{decision_id}", response_model=DecisionOut)
async def get_decision(
    decision_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> DecisionOut:
    return await _view(db, principal.tenant_id, decision_id)


@router.post("/decisions/{decision_id}/override-review", response_model=DecisionOut)
async def review_override(
    decision_id: uuid.UUID, body: OverrideReviewIn, principal: AdminPrincipal, db: DatabaseDep
) -> DecisionOut:
    async with db.tenant_session(principal.tenant_id) as session:
        await service.review_override(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            decision_id=decision_id,
            approve=body.decision == "approve",
            reason=body.reason,
        )
    return await _view(db, principal.tenant_id, decision_id)


@router.post("/decisions/{decision_id}/reported-done", response_model=DecisionOut)
async def report_done(
    decision_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> DecisionOut:
    async with db.tenant_session(principal.tenant_id) as session:
        await service.report_done(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            decision_id=decision_id,
        )
    return await _view(db, principal.tenant_id, decision_id)


@router.get("/variants/{variant_id}/history", response_model=list[HistoryItemOut])
async def variant_history(
    variant_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> list[HistoryItemOut]:
    async with db.tenant_session(principal.tenant_id) as session:
        items = await history.variant_history(session, variant_id)
    return [
        HistoryItemOut(
            recommendation=RecommendationSummary.model_validate(item.recommendation),
            decisions=[_out(v) for v in item.decisions],
        )
        for item in items
    ]
