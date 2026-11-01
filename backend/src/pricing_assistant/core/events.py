"""Domain events, the envelope that carries them, and transactional outbox publishing.

``publish`` writes the event to ``outbox_event`` in the caller's transaction, so an event
exists if and only if the state change that caused it was committed (design D3).
"""

import builtins
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.correlation import get_correlation_id
from pricing_assistant.core.db import Base
from pricing_assistant.core.ids import new_id


class DomainEvent(BaseModel):
    """Base for typed event payloads. Subclasses set ``event_type`` and ``event_version``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: ClassVar[str]
    event_version: ClassVar[int] = 1


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: uuid.UUID
    type: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    tenant_id: uuid.UUID
    occurred_at: datetime
    correlation_id: str
    causation_id: uuid.UUID | None = None
    payload: dict[str, Any]

    def decode[E: DomainEvent](self, event_class: builtins.type[E]) -> E:
        if self.type != event_class.event_type:
            raise ValueError(f"envelope type {self.type!r} is not {event_class.event_type!r}")
        return event_class.model_validate(self.payload)


class OutboxEventRow(Base):
    __tablename__ = "outbox_event"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    type: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(Text)
    causation_id: Mapped[uuid.UUID | None]
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def envelope(self) -> EventEnvelope:
        return EventEnvelope(
            event_id=self.id,
            type=self.type,
            version=self.version,
            tenant_id=self.tenant_id,
            occurred_at=self.occurred_at,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            payload=self.payload,
        )


async def publish(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event: DomainEvent,
    causation_id: uuid.UUID | None = None,
) -> EventEnvelope:
    """Stage ``event`` in the outbox within the current transaction."""
    envelope = EventEnvelope(
        event_id=new_id(),
        type=event.event_type,
        version=event.event_version,
        tenant_id=tenant_id,
        occurred_at=datetime.now(UTC),
        correlation_id=get_correlation_id(),
        causation_id=causation_id,
        payload=event.model_dump(mode="json"),
    )
    session.add(
        OutboxEventRow(
            id=envelope.event_id,
            tenant_id=tenant_id,
            type=envelope.type,
            version=envelope.version,
            payload=envelope.payload,
            occurred_at=envelope.occurred_at,
            correlation_id=envelope.correlation_id,
            causation_id=causation_id,
        )
    )
    await session.flush()
    return envelope
