"""Recomputation triggers, the debounced recompute actor and explanation wording (9.5, 9.6, 8.5).

Any input change requests a recompute of the affected variants. Requests are debounced per
variant: the first request in a 5-second window schedules one delayed recompute; later requests
in the window are absorbed, so a burst of observations yields one new recommendation computed
from the latest data. A periodic refresh catches evidence that ages out without any event.
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.api import list_variants
from pricing_assistant.catalog.events import CostChanged, RuleVersionCreated, VariantsChanged
from pricing_assistant.collection.events import FetchFailed, ObservationRecorded
from pricing_assistant.core.consumer import Handler
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.logging import get_logger
from pricing_assistant.llm.api import LLMPort, RephraseRequest
from pricing_assistant.matching.events import MatchChanged
from pricing_assistant.pricing.events import OutlierConfirmed, RecommendationCreated
from pricing_assistant.pricing.models import RecommendationRow
from pricing_assistant.pricing.service import recompute
from pricing_assistant.sources.api import TrackedOfferRow
from pricing_assistant.sources.events import SourceStatusChanged

DEBOUNCE_MS = 5_000
RECOMPUTE_TYPE = "pricing.recompute.requested"
log = get_logger(__name__)

# (envelope, delay_ms) → enqueue on the recompute actor
SendRecompute = Callable[[EventEnvelope, int], None]


class RecomputeScheduler:
    def __init__(self, redis: Callable[[], Redis], send: SendRecompute) -> None:
        self._redis = redis
        self._send = send

    async def request(
        self, tenant_id: uuid.UUID, variant_ids: Iterable[uuid.UUID], *, correlation_id: str
    ) -> int:
        scheduled = 0
        for variant_id in dict.fromkeys(variant_ids):
            key = f"pa:recompute:{tenant_id}:{variant_id}"
            if await self._redis().set(key, "1", nx=True, px=DEBOUNCE_MS):
                self._send(
                    EventEnvelope(
                        event_id=new_id(),
                        type=RECOMPUTE_TYPE,
                        version=1,
                        tenant_id=tenant_id,
                        occurred_at=datetime.now(UTC),
                        correlation_id=correlation_id,
                        payload={"variant_id": str(variant_id)},
                    ),
                    DEBOUNCE_MS,
                )
                scheduled += 1
        return scheduled


async def _variants_for_rule(session: AsyncSession, event: RuleVersionCreated) -> list[uuid.UUID]:
    if event.scope == "variant" and event.scope_key:
        return [uuid.UUID(event.scope_key)]
    variants = await list_variants(session)
    if event.scope == "category":
        return [v.id for v in variants if v.category == event.scope_key]
    return [v.id for v in variants]


async def _variants_for_source(session: AsyncSession, source_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(TrackedOfferRow.variant_id).where(TrackedOfferRow.source_id == source_id).distinct()
    )
    return list(rows.all())


def _match_variants(envelope: EventEnvelope) -> list[uuid.UUID]:
    event = envelope.decode(MatchChanged)
    return [v for v in (event.variant_id, event.previous_variant_id) if v is not None]


_DIRECT: dict[str, Callable[[EventEnvelope], list[uuid.UUID]]] = {
    ObservationRecorded.event_type: lambda e: [e.decode(ObservationRecorded).variant_id],
    FetchFailed.event_type: lambda e: [e.decode(FetchFailed).variant_id],
    MatchChanged.event_type: _match_variants,
    OutlierConfirmed.event_type: lambda e: [e.decode(OutlierConfirmed).variant_id],
    CostChanged.event_type: lambda e: e.decode(CostChanged).variant_ids,
    VariantsChanged.event_type: lambda e: e.decode(VariantsChanged).variant_ids,
}


async def affected_variants(session: AsyncSession, envelope: EventEnvelope) -> list[uuid.UUID]:
    """Which variants an input-changing event affects."""
    if envelope.type in _DIRECT:
        return _DIRECT[envelope.type](envelope)
    if envelope.type == RuleVersionCreated.event_type:
        return await _variants_for_rule(session, envelope.decode(RuleVersionCreated))
    if envelope.type == SourceStatusChanged.event_type:
        return await _variants_for_source(session, envelope.decode(SourceStatusChanged).source_id)
    return []


TRIGGER_EVENTS = (
    ObservationRecorded.event_type,
    FetchFailed.event_type,
    MatchChanged.event_type,
    OutlierConfirmed.event_type,
    CostChanged.event_type,
    VariantsChanged.event_type,
    RuleVersionCreated.event_type,
    SourceStatusChanged.event_type,
)


def trigger_handler(scheduler: RecomputeScheduler) -> Handler:
    async def handle(session: AsyncSession, envelope: EventEnvelope) -> None:
        variants = await affected_variants(session, envelope)
        if variants:
            await scheduler.request(
                envelope.tenant_id, variants, correlation_id=envelope.correlation_id
            )

    return handle


def recompute_handler(
    database: Callable[[], Database],
) -> Callable[[EventEnvelope], Awaitable[None]]:
    async def handle(envelope: EventEnvelope) -> None:
        variant_id = uuid.UUID(envelope.payload["variant_id"])
        async with database().tenant_session(envelope.tenant_id) as session:
            row = await recompute(session, envelope.tenant_id, variant_id)
        if row is not None:
            log.info(
                "pricing.recommendation_created", variant_id=str(variant_id), outcome=row.outcome
            )

    return handle


async def refresh_aging(
    db: Database, scheduler: RecomputeScheduler, *, older_than: timedelta = timedelta(minutes=10)
) -> int:
    """Re-evaluate current recommendations computed more than ``older_than`` ago."""
    cutoff = datetime.now(UTC) - older_than
    requested = 0
    for tenant_id in await db.active_tenant_ids():
        async with db.tenant_session(tenant_id) as session:
            variants = (
                await session.scalars(
                    select(RecommendationRow.variant_id).where(
                        RecommendationRow.superseded_by.is_(None),
                        RecommendationRow.evaluated_at < cutoff,
                    )
                )
            ).all()
        requested += await scheduler.request(
            tenant_id, variants, correlation_id=f"refresh-{new_id()}"
        )
    return requested


MAX_REPHRASE_CHARS = 2_000


def rephrase_handler(llm: LLMPort) -> Handler:
    """After a recommendation is stored, ask for a plainer wording of its explanation.

    Runs outside the computation: the recommendation's numbers are already final. The wording is
    stored only if the port's number check passed; otherwise the deterministic text is shown.
    """

    async def handle(session: AsyncSession, envelope: EventEnvelope) -> None:
        if not llm.enabled:
            return
        event = envelope.decode(RecommendationCreated)
        row = await session.get(RecommendationRow, event.recommendation_id)
        if (
            row is None
            or row.superseded_by is not None
            or row.explanation_llm is not None
            or len(row.explanation) > MAX_REPHRASE_CHARS
        ):
            return
        result = await llm.rephrase_explanation(
            envelope.tenant_id, RephraseRequest(text=row.explanation)
        )
        if result.ok and result.value is not None:
            row.explanation_llm = result.value.text

    return handle
