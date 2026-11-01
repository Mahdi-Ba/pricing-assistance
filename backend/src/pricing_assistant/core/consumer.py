"""Idempotent event consumers.

A consumer records ``(consumer, event_id)`` in ``processed_event`` in the same transaction as
its own writes. A redelivered event finds the row and is skipped, so handlers run exactly once
per event even though delivery is at-least-once.
"""

import functools
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.correlation import set_correlation_id
from pricing_assistant.core.db import Base, Database
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.logging import get_logger

Handler = Callable[[AsyncSession, EventEnvelope], Awaitable[None]]
log = get_logger(__name__)


class ProcessedEventRow(Base):
    __tablename__ = "processed_event"

    consumer: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


async def consume(db: Database, consumer: str, envelope: EventEnvelope, handler: Handler) -> bool:
    """Run ``handler`` once per (consumer, event). Returns False for a duplicate delivery."""
    set_correlation_id(envelope.correlation_id)
    async with db.tenant_session(envelope.tenant_id) as session:
        claimed = await session.scalar(
            insert(ProcessedEventRow)
            .values(consumer=consumer, event_id=envelope.event_id, tenant_id=envelope.tenant_id)
            .on_conflict_do_nothing()
            .returning(ProcessedEventRow.event_id)
        )
        if claimed is None:
            log.info("event.duplicate_skipped", consumer=consumer, event_id=str(envelope.event_id))
            return False
        log.info(
            "event.consumed",
            consumer=consumer,
            event_type=envelope.type,
            event_id=str(envelope.event_id),
        )
        await handler(session, envelope)
    return True


def idempotent_consumer(
    consumer: str, db_provider: Callable[[], Database]
) -> Callable[[Handler], Callable[[dict[str, Any]], Awaitable[bool]]]:
    """Wrap a handler as a Dramatiq-compatible async callable taking the envelope as a dict."""

    def decorate(handler: Handler) -> Callable[[dict[str, Any]], Awaitable[bool]]:
        @functools.wraps(handler)
        async def run(message: dict[str, Any]) -> bool:
            envelope = EventEnvelope.model_validate(message)
            return await consume(db_provider(), consumer, envelope, handler)

        return run

    return decorate
