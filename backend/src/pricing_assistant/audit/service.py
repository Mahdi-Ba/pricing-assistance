"""Recording audit events inside the caller's transaction."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.models import AuditEventRow
from pricing_assistant.core.correlation import get_correlation_id
from pricing_assistant.core.ids import new_id


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class AuditActor:
    subject: str
    username: str


SYSTEM_ACTOR = AuditActor(subject="system", username="system")


def _summary(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    jsonable: dict[str, Any] = to_jsonable_python(dict(value))
    return jsonable


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    action: str,
    target_type: str,
    target_id: str | uuid.UUID | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
) -> uuid.UUID:
    """Append an audit event in the current transaction; it commits or rolls back with it."""
    event_id = new_id()
    session.add(
        AuditEventRow(
            id=event_id,
            tenant_id=tenant_id,
            actor_subject=actor.subject,
            actor_username=actor.username,
            action=action,
            outcome=outcome.value,
            target_type=target_type,
            target_id=None if target_id is None else str(target_id),
            before=_summary(before),
            after=_summary(after),
            reason=reason,
            correlation_id=get_correlation_id(),
        )
    )
    await session.flush()
    return event_id


async def list_events(
    session: AsyncSession,
    *,
    action: str | None = None,
    target_id: str | None = None,
    limit: int = 100,
) -> list[AuditEventRow]:
    query = select(AuditEventRow).order_by(AuditEventRow.occurred_at, AuditEventRow.id)
    if action is not None:
        query = query.where(AuditEventRow.action == action)
    if target_id is not None:
        query = query.where(AuditEventRow.target_id == target_id)
    return list((await session.scalars(query.limit(limit))).all())
