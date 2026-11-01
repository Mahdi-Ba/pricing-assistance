"""Retention purges (task 5.11), run by the scheduler as the maintenance database role.

- Evidence snapshots older than the tenant's ``evidence_retention_days`` (default 90) are
  deleted from object storage; their registry rows stay, marked ``expired_at``, so evidence
  links show that the snapshot expired.
- If the tenant sets ``observation_retention_days``, older observations (and their fetch
  attempts and claims) are deleted. Recommendations that referenced them stay and report
  ``inputs_purged``.

Each purge writes a ``purge_log`` row and an audit event with counts. The application role
cannot delete observations; only this job's role can.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, Integer, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.audit.api import SYSTEM_ACTOR, record
from pricing_assistant.collection.evidence import EvidenceObjectRow, EvidenceStore
from pricing_assistant.collection.models import FetchAttemptRow, FetchClaimRow, ObservationRow
from pricing_assistant.core import tenant_settings
from pricing_assistant.core.db import Base, Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.logging import get_logger

BATCH = 1_000
log = get_logger(__name__)


class PurgeLogRow(Base):
    __tablename__ = "purge_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    kind: Mapped[str] = mapped_column(Text)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_count: Mapped[int] = mapped_column(Integer)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@dataclass(frozen=True, slots=True)
class PurgeResult:
    tenant_id: uuid.UUID
    evidence_expired: int
    observations_deleted: int


async def _log(
    session: AsyncSession, tenant_id: uuid.UUID, kind: str, cutoff: datetime, count: int
) -> None:
    session.add(
        PurgeLogRow(id=new_id(), tenant_id=tenant_id, kind=kind, cutoff=cutoff, deleted_count=count)
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=SYSTEM_ACTOR,
        action=f"retention.{kind}.purged",
        target_type="tenant",
        target_id=tenant_id,
        after={"cutoff": cutoff.isoformat(), "deleted": count},
    )


async def _expire_evidence(
    session: AsyncSession, store: EvidenceStore, cutoff: datetime, now: datetime
) -> int:
    rows = (
        await session.scalars(
            select(EvidenceObjectRow)
            .where(EvidenceObjectRow.created_at < cutoff, EvidenceObjectRow.expired_at.is_(None))
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in rows:
        await store.delete(row.object_key)
        row.expired_at = now
    return len(rows)


async def _delete_observations(session: AsyncSession, cutoff: datetime) -> int:
    deleted = (
        await session.scalars(
            delete(ObservationRow)
            .where(ObservationRow.observed_at < cutoff)
            .returning(ObservationRow.id)
        )
    ).all()
    await session.execute(delete(FetchClaimRow).where(FetchClaimRow.window_start < cutoff))
    still_referenced = select(ObservationRow.fetch_attempt_id)
    await session.execute(
        delete(FetchAttemptRow).where(
            FetchAttemptRow.finished_at < cutoff, FetchAttemptRow.id.not_in(still_referenced)
        )
    )
    return len(deleted)


async def purge(
    maintenance_db: Database, store: EvidenceStore, *, now: datetime | None = None
) -> list[PurgeResult]:
    now = now or datetime.now(UTC)
    results: list[PurgeResult] = []
    for tenant_id in await maintenance_db.active_tenant_ids():
        async with maintenance_db.tenant_session(tenant_id) as session:
            settings = await tenant_settings.load(session, tenant_id)
            evidence_cutoff = now - timedelta(days=settings.evidence_retention_days)
            expired = await _expire_evidence(session, store, evidence_cutoff, now)
            if expired:
                await _log(session, tenant_id, "evidence", evidence_cutoff, expired)
            deleted = 0
            if settings.observation_retention_days is not None:
                cutoff = now - timedelta(days=settings.observation_retention_days)
                deleted = await _delete_observations(session, cutoff)
                if deleted:
                    await _log(session, tenant_id, "observation", cutoff, deleted)
        results.append(PurgeResult(tenant_id, expired, deleted))
        if expired or deleted:
            log.info(
                "retention.purged",
                tenant_id=str(tenant_id),
                evidence_expired=expired,
                observations_deleted=deleted,
            )
    return results


async def missing_observations(
    session: AsyncSession, observation_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Ids among ``observation_ids`` that no longer exist (purged)."""
    if not observation_ids:
        return set()
    present = set(
        (
            await session.scalars(
                select(ObservationRow.id).where(ObservationRow.id.in_(observation_ids))
            )
        ).all()
    )
    return set(observation_ids) - present
