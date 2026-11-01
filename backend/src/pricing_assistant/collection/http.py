"""HTTP API of the collection module."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict

from pricing_assistant.collection.evidence import EvidenceStore, presigned_url
from pricing_assistant.collection.health import source_health
from pricing_assistant.collection.models import RecheckRequestRow
from pricing_assistant.collection.recheck import request_recheck
from pricing_assistant.core.deps import DatabaseDep, RedisDep
from pricing_assistant.core.errors import NotFound
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.iam.api import AdminPrincipal, ExpertPrincipal, actor_of
from pricing_assistant.sources.api import RecheckBudget, SourceRateLimiter

router = APIRouter(route_class=IdempotentRoute, tags=["collection"])


class EvidenceLinkOut(BaseModel):
    id: uuid.UUID
    kind: str
    content_type: str
    url: str
    expires_in_seconds: int


@router.get("/evidence/{evidence_id}", response_model=EvidenceLinkOut)
async def evidence_link(
    evidence_id: uuid.UUID, request: Request, principal: ExpertPrincipal, db: DatabaseDep
) -> EvidenceLinkOut:
    store: EvidenceStore = request.app.state.evidence_store
    async with db.tenant_session(principal.tenant_id) as session:
        row, url = await presigned_url(session, store, evidence_id)
    return EvidenceLinkOut(
        id=row.id,
        kind=row.kind,
        content_type=row.content_type,
        url=url,
        expires_in_seconds=request.app.state.settings.s3_presign_ttl_seconds,
    )


class RecheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tracked_offer_id: uuid.UUID
    requested_by: str
    status: Literal["pending", "completed", "failed"]
    fetch_attempt_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None


@router.post(
    "/tracked-offers/{tracked_offer_id}/recheck",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RecheckOut,
)
async def recheck(
    tracked_offer_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep, redis: RedisDep
) -> RecheckRequestRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await request_recheck(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            tracked_offer_id=tracked_offer_id,
            limiter=SourceRateLimiter(redis),
            budget=RecheckBudget(redis),
        )


@router.get("/rechecks/{recheck_id}", response_model=RecheckOut)
async def recheck_status(
    recheck_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> RecheckRequestRow:
    async with db.tenant_session(principal.tenant_id) as session:
        row = await session.get(RecheckRequestRow, recheck_id)
    if row is None:
        raise NotFound("Re-check not found", message_fa="درخواست بررسی مجدد یافت نشد.")
    return row


class SourceHealthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: uuid.UUID
    name: str
    status: str
    period_hours: int
    requests: int
    successes: int
    success_rate: float | None
    errors: dict[str, int]
    blocked: int
    data_age_median_seconds: int | None
    data_age_max_seconds: int | None
    offers_without_observation: int
    estimated_cost_rial: int


@router.get("/sources-health", response_model=list[SourceHealthOut])
async def sources_health(
    principal: AdminPrincipal,
    db: DatabaseDep,
    hours: Annotated[int, Query(ge=1, le=24 * 31)] = 24,
) -> list[SourceHealthOut]:
    async with db.tenant_session(principal.tenant_id) as session:
        report = await source_health(session, hours=hours)
    return [SourceHealthOut.model_validate(item) for item in report]
