"""HTTP API for expert match decisions (tasks 7.6, 11.5)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, StringConstraints

from pricing_assistant.core.deps import DatabaseDep
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.iam.api import ExpertPrincipal, actor_of
from pricing_assistant.matching.models import MatchVersionRow
from pricing_assistant.matching.service import ExpertAction, decide

router = APIRouter(route_class=IdempotentRoute, tags=["matching"])


class MatchDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ExpertAction
    reason: Annotated[str, StringConstraints(max_length=1_000)] | None = None
    target_variant_id: uuid.UUID | None = None


class MatchVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tracked_offer_id: uuid.UUID
    seller_key: str
    variant_id: uuid.UUID
    state: Literal["proposed", "confirmed", "rejected", "needs_review"]
    flags: list[str]
    confidence_bp: int
    decided_by: Literal["rule", "llm", "human"]
    actor: str
    reason: str | None
    previous_version_id: uuid.UUID | None
    is_current: bool
    created_at: datetime


@router.post("/matches/{match_version_id}/decision", response_model=MatchVersionOut)
async def decide_match(
    match_version_id: uuid.UUID, body: MatchDecisionIn, principal: ExpertPrincipal, db: DatabaseDep
) -> MatchVersionRow:
    """Confirm, reject or re-assign; each creates a new audited version and triggers recompute."""
    async with db.tenant_session(principal.tenant_id) as session:
        return await decide(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            match_version_id=match_version_id,
            action=body.action,
            reason=body.reason,
            target_variant_id=body.target_variant_id,
        )
