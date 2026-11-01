"""Scheduler tick: enqueue due fetches (design D6, task 5.2).

``tracked_offer.next_due_at`` is the source of truth. Each tick locks due offers with
``FOR UPDATE SKIP LOCKED`` (so concurrent ticks never take the same offer), publishes one fetch
request per offer for the window ``window_start = next_due_at`` and advances ``next_due_at`` by
the source's interval for the variant's importance tier. The worker executes a window at most
once (``fetch_claim``), so a duplicate request for the same window is harmless.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from pricing_assistant.catalog.api import ImportanceTier, list_variants
from pricing_assistant.collection.events import BrowserFetchRequested, FetchRequested
from pricing_assistant.collection.models import FetchTrigger
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import publish
from pricing_assistant.core.logging import get_logger
from pricing_assistant.sources.api import (
    RetrievalMethod,
    SourceRow,
    SourceStatus,
    TrackedOfferRow,
    TrackedOfferStatus,
)

log = get_logger(__name__)
COLLECTABLE = (SourceStatus.UNDER_EVALUATION.value, SourceStatus.APPROVED.value)


def interval_for(source: SourceRow, tier: ImportanceTier) -> timedelta:
    seconds = {
        ImportanceTier.A: source.interval_a_seconds,
        ImportanceTier.B: source.interval_b_seconds,
        ImportanceTier.C: source.interval_c_seconds,
    }[tier]
    return timedelta(seconds=seconds)


def request_for(source: SourceRow, **fields: object) -> FetchRequested:
    if RetrievalMethod(source.method) is RetrievalMethod.RENDERED_PAGE:
        return BrowserFetchRequested.model_validate(fields)
    return FetchRequested.model_validate(fields)


async def schedule_due(db: Database, *, now: datetime | None = None, batch_size: int = 500) -> int:
    """Publish fetch requests for every due offer of every active tenant."""
    now = now or datetime.now(UTC)
    scheduled = 0
    for tenant_id in await db.active_tenant_ids():
        async with db.tenant_session(tenant_id) as session:
            rows = (
                await session.execute(
                    select(TrackedOfferRow, SourceRow)
                    .join(SourceRow, SourceRow.id == TrackedOfferRow.source_id)
                    .where(
                        TrackedOfferRow.status == TrackedOfferStatus.ACTIVE.value,
                        TrackedOfferRow.next_due_at <= now,
                        SourceRow.status.in_(COLLECTABLE),
                    )
                    .order_by(TrackedOfferRow.next_due_at)
                    .limit(batch_size)
                    .with_for_update(of=TrackedOfferRow, skip_locked=True)
                )
            ).all()
            if not rows:
                continue
            tiers = {
                v.id: v.importance_tier
                for v in await list_variants(session, [offer.variant_id for offer, _ in rows])
            }
            for offer, source in rows:
                window_start = offer.next_due_at or now
                interval = interval_for(source, tiers.get(offer.variant_id, ImportanceTier.B))
                next_due = window_start + interval
                offer.next_due_at = next_due if next_due > now else now + interval
                await publish(
                    session,
                    tenant_id=tenant_id,
                    event=request_for(
                        source,
                        tracked_offer_id=offer.id,
                        window_start=window_start,
                        trigger=FetchTrigger.SCHEDULED.value,
                    ),
                )
                scheduled += 1
    if scheduled:
        log.info("collection.fetches_scheduled", count=scheduled)
    return scheduled
