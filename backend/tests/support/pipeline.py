"""Drives pending outbox events through the real handlers, as the relay and workers would."""

from sqlalchemy import select

from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.runtime import CollectionRuntime
from pricing_assistant.core.consumer import Handler, consume
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope, OutboxEventRow
from pricing_assistant.matching.consumers import on_attributes_updated, on_observation_recorded

IDEMPOTENT: dict[str, list[tuple[str, Handler]]] = {
    "observation.recorded": [("matching.normalize", on_observation_recorded)],
    "offer.attributes.updated": [("matching.match", on_attributes_updated)],
}
RAW_FETCH = {"fetch.requested", "fetch.requested.browser"}


async def drain(
    db: Database,
    tenant_ids: list[object],
    runtime: CollectionRuntime | None = None,
    *,
    extra: dict[str, list[tuple[str, Handler]]] | None = None,
    flush_limiter: object = None,
    max_rounds: int = 20,
) -> int:
    """Process undispatched events (marking them dispatched) until none are left."""
    processed = 0
    for _ in range(max_rounds):
        batch: list[EventEnvelope] = []
        for tenant_id in tenant_ids:
            async with db.tenant_session(tenant_id) as session:  # type: ignore[arg-type]
                rows = (
                    await session.scalars(
                        select(OutboxEventRow)
                        .where(OutboxEventRow.dispatched_at.is_(None))
                        .order_by(OutboxEventRow.occurred_at)
                        .with_for_update()
                    )
                ).all()
                for row in rows:
                    batch.append(row.envelope())
                    row.dispatched_at = row.occurred_at
        if not batch:
            return processed
        for envelope in batch:
            if envelope.type in RAW_FETCH and runtime is not None:
                if flush_limiter is not None:
                    await flush_limiter.flushdb()  # type: ignore[attr-defined]
                await handle_fetch(runtime, envelope)
            for name, handler in IDEMPOTENT.get(envelope.type, []) + (extra or {}).get(
                envelope.type, []
            ):
                await consume(db, name, envelope, handler)
            processed += 1
    return processed
