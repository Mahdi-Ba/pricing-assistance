"""HTTP API of the pricing module: recommendations, replay and outlier confirmation."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from pricing_assistant.core.deps import DatabaseDep
from pricing_assistant.core.errors import NotFound
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.iam.api import ExpertPrincipal, actor_of
from pricing_assistant.pricing.models import RecommendationRow
from pricing_assistant.pricing.service import confirm_outlier, current_recommendation, replay

router = APIRouter(route_class=IdempotentRoute, tags=["pricing"])


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID
    outcome: Literal["increase", "decrease", "hold", "insufficient_data", "floor_conflict"]
    reason_code: str
    flags: list[str]
    suggested_price_rial: int | None
    our_price_rial: int | None
    floor_rial: int | None
    ceiling_rial: int | None
    market_ref_rial: int | None
    market_ref_observation_id: uuid.UUID | None
    median_rial: int | None
    qualifying_count: int
    excluded_outlier_ids: list[uuid.UUID]
    profit_current_rial: int | None
    profit_suggested_rial: int | None
    explanation: str  # deterministic text, always present
    explanation_llm: str | None  # optional LLM rewording that kept every number
    observation_ids: list[uuid.UUID]
    match_version_ids: list[uuid.UUID]
    cost_record_id: uuid.UUID | None
    rule_version_ids: list[uuid.UUID]
    engine_version: str
    evaluated_at: datetime
    superseded_by: uuid.UUID | None
    created_at: datetime


class ReplayOut(BaseModel):
    recommendation_id: uuid.UUID
    identical: bool
    inputs_purged: bool
    stored: dict[str, Any]
    recomputed: dict[str, Any] | None


class OutlierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class OutlierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    observation_id: uuid.UUID
    variant_id: uuid.UUID
    actor: str
    reason: str
    created_at: datetime


@router.get("/recommendations/{recommendation_id}", response_model=RecommendationOut)
async def get_recommendation(
    recommendation_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> RecommendationRow:
    async with db.tenant_session(principal.tenant_id) as session:
        row = await session.get(RecommendationRow, recommendation_id)
    if row is None:
        raise NotFound("Recommendation not found", message_fa="پیشنهاد قیمت یافت نشد.")
    return row


@router.get("/variants/{variant_id}/recommendation", response_model=RecommendationOut)
async def variant_recommendation(
    variant_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> RecommendationRow:
    async with db.tenant_session(principal.tenant_id) as session:
        row = await current_recommendation(session, variant_id)
    if row is None:
        raise NotFound(
            "No recommendation yet", message_fa="هنوز پیشنهادی برای این کالا محاسبه نشده است."
        )
    return row


@router.post("/recommendations/{recommendation_id}/replay", response_model=ReplayOut)
async def replay_recommendation(
    recommendation_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> ReplayOut:
    async with db.tenant_session(principal.tenant_id) as session:
        result = await replay(session, recommendation_id)
    return ReplayOut(
        recommendation_id=result.recommendation_id,
        identical=result.identical,
        inputs_purged=result.inputs_purged,
        stored=result.stored,
        recomputed=result.recomputed,
    )


@router.post(
    "/observations/{observation_id}/outlier-confirmation",
    status_code=status.HTTP_201_CREATED,
    response_model=OutlierOut,
)
async def outlier_confirmation(
    observation_id: uuid.UUID, body: OutlierIn, principal: ExpertPrincipal, db: DatabaseDep
) -> object:
    async with db.tenant_session(principal.tenant_id) as session:
        return await confirm_outlier(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            observation_id=observation_id,
            reason=body.reason,
        )
