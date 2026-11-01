"""End-to-end pricing harness: real handlers, captured (non-delayed) recompute messages."""

import uuid
from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy import select

from pricing_assistant.catalog.rules import (
    SUGGESTED_DEFAULTS,
    RuleFields,
    RuleScope,
    create_version,
)
from pricing_assistant.collection.runtime import CollectionRuntime
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.matching.api import MatchVersionRow
from pricing_assistant.matching.service import ExpertAction, decide
from pricing_assistant.pricing.consumers import (
    RecomputeScheduler,
    recompute_handler,
    trigger_handler,
)
from tests.support.pipeline import drain
from tests.support.seed import ADMIN


@dataclass
class Captured:
    messages: list[tuple[EventEnvelope, int]] = field(default_factory=list)

    def __call__(self, envelope: EventEnvelope, delay_ms: int) -> None:
        self.messages.append((envelope, delay_ms))


@dataclass
class PricingHarness:
    db: Database
    redis: Redis
    tenant_id: uuid.UUID
    collection: CollectionRuntime | None = None
    sent: Captured = field(default_factory=Captured)

    @property
    def scheduler(self) -> RecomputeScheduler:
        return RecomputeScheduler(lambda: self.redis, self.sent)

    async def settle(self) -> None:
        """Process all pending events and run every requested recompute (ignoring the delay)."""
        handler = recompute_handler(lambda: self.db)
        extra = {t: [("pricing.triggers", trigger_handler(self.scheduler))] for t in _TRIGGERS}
        for _ in range(10):
            await drain(
                self.db, [self.tenant_id], self.collection, extra=extra, flush_limiter=self.redis
            )
            if not self.sent.messages:
                return
            pending, self.sent.messages = self.sent.messages, []
            for envelope, _delay in pending:
                await handler(envelope)
            await self.redis.flushdb()  # debounce windows elapsed


async def default_rule(db: Database, tenant_id: uuid.UUID, **overrides: object) -> None:
    fields = SUGGESTED_DEFAULTS.overlay(RuleFields(vat_rate_bp=0)).overlay(RuleFields(**overrides))  # type: ignore[arg-type]
    async with db.tenant_session(tenant_id) as session:
        await create_version(
            session,
            tenant_id=tenant_id,
            actor=ADMIN,
            scope=RuleScope.DEFAULT,
            scope_key=None,
            values=fields,
            reason="test",
        )


async def confirm_all_matches(db: Database, tenant_id: uuid.UUID) -> None:
    async with db.tenant_session(tenant_id) as session:
        current = (
            await session.scalars(
                select(MatchVersionRow).where(
                    MatchVersionRow.is_current.is_(True), MatchVersionRow.state != "confirmed"
                )
            )
        ).all()
    for match in current:
        async with db.tenant_session(tenant_id) as session:
            await decide(
                session,
                tenant_id=tenant_id,
                actor=ADMIN,
                match_version_id=match.id,
                action=ExpertAction.CONFIRM,
                reason="test",
            )


_TRIGGERS = (
    "observation.recorded",
    "fetch.failed",
    "match.changed",
    "outlier.confirmed",
    "catalog.cost.changed",
    "catalog.variants.changed",
    "rule.version.created",
    "source.status.changed",
)
__all__ = ["MatchVersionRow", "PricingHarness", "confirm_all_matches", "default_rule"]
