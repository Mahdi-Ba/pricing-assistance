"""Review sessions: how long an expert spends on one queue item (task 11.6, review-time KPI).

The detail view opens a session when it mounts, reports activity while the expert works, and
closes it when the decision is submitted or the view is left. A session without activity for
15 minutes counts as ended 15 minutes after its last activity, whenever it is finally closed,
so an abandoned tab does not inflate the review time.
"""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.catalog.api import variant_exists
from pricing_assistant.core.db import Base, Database
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.ids import new_id
from pricing_assistant.iam.api import Principal

IDLE_TIMEOUT = timedelta(minutes=15)


class CloseReason(StrEnum):
    DECISION = "decision"
    LEFT = "left"
    IDLE = "idle"


class ReviewSessionRow(Base):
    __tablename__ = "review_session"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("recommendation.id"))
    user_subject: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[str | None] = mapped_column(Text)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decision.id"))

    @property
    def duration_seconds(self) -> int | None:
        if self.closed_at is None:
            return None
        return int((self.closed_at - self.opened_at).total_seconds())


def _idle_end(row: ReviewSessionRow) -> datetime:
    return row.last_activity_at + IDLE_TIMEOUT


async def open_session(
    session: AsyncSession,
    *,
    principal: Principal,
    variant_id: uuid.UUID,
    recommendation_id: uuid.UUID | None,
    now: datetime | None = None,
) -> ReviewSessionRow:
    if not await variant_exists(session, variant_id):
        raise NotFound("Variant not found", message_fa="کالا یافت نشد.")
    now = now or datetime.now(UTC)
    row = ReviewSessionRow(
        id=new_id(),
        tenant_id=principal.tenant_id,
        variant_id=variant_id,
        recommendation_id=recommendation_id,
        user_subject=principal.subject,
        username=principal.username,
        opened_at=now,
        last_activity_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def _own_open(
    session: AsyncSession, principal: Principal, session_id: uuid.UUID
) -> ReviewSessionRow:
    row = await session.get(ReviewSessionRow, session_id, with_for_update=True)
    if row is None or row.user_subject != principal.subject:
        raise NotFound("Review session not found", message_fa="جلسه بررسی یافت نشد.")
    if row.closed_at is not None:
        raise Conflict(
            "The review session is closed",
            code="review_session_closed",
            message_fa="این جلسه بررسی بسته شده است.",
        )
    return row


async def record_activity(
    session: AsyncSession,
    *,
    principal: Principal,
    session_id: uuid.UUID,
    now: datetime | None = None,
) -> ReviewSessionRow:
    now = now or datetime.now(UTC)
    row = await _own_open(session, principal, session_id)
    if now > _idle_end(row):  # came back after the idle limit: the old session ended then
        row.closed_at, row.close_reason = _idle_end(row), CloseReason.IDLE.value
    else:
        row.last_activity_at = max(row.last_activity_at, now)
    await session.flush()
    return row


async def close_session(
    session: AsyncSession,
    *,
    principal: Principal,
    session_id: uuid.UUID,
    reason: CloseReason,
    decision_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> ReviewSessionRow:
    if reason is CloseReason.IDLE:
        raise ValidationFailed(
            "Idle closing is automatic", message_fa="بستن خودکار قابل درخواست نیست."
        )
    now = now or datetime.now(UTC)
    row = await _own_open(session, principal, session_id)
    if now > _idle_end(row):
        row.closed_at, row.close_reason = _idle_end(row), CloseReason.IDLE.value
    else:
        row.closed_at, row.close_reason = now, reason.value
        row.decision_id = decision_id if reason is CloseReason.DECISION else None
    await session.flush()
    return row


async def close_idle(db: Database, *, now: datetime | None = None) -> int:
    """Scheduler job: end sessions idle for longer than the limit at last activity + limit."""
    now = now or datetime.now(UTC)
    closed = 0
    for tenant_id in await db.active_tenant_ids():
        async with db.tenant_session(tenant_id) as session:
            rows = (
                await session.scalars(
                    select(ReviewSessionRow)
                    .where(
                        ReviewSessionRow.closed_at.is_(None),
                        ReviewSessionRow.last_activity_at < now - IDLE_TIMEOUT,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.closed_at, row.close_reason = _idle_end(row), CloseReason.IDLE.value
                closed += 1
    return closed
