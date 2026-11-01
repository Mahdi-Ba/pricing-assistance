"""A CollectionRuntime wired to test doubles."""

from dataclasses import dataclass, field

from redis.asyncio import Redis

from pricing_assistant.collection.evidence import EvidenceStore
from pricing_assistant.collection.runtime import CollectionRuntime
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.settings import get_settings
from tests.support.fakes import FixedRegistry, RecordingConnector


@dataclass
class Requeued:
    items: list[tuple[EventEnvelope, int]] = field(default_factory=list)

    def __call__(self, envelope: EventEnvelope, delay_ms: int) -> None:
        self.items.append((envelope, delay_ms))


async def collection_runtime(
    db: Database, redis: Redis, connector: RecordingConnector
) -> tuple[CollectionRuntime, Requeued]:
    store = EvidenceStore(get_settings())
    await store.ensure_bucket()
    requeued = Requeued()
    registry = FixedRegistry(connector)
    runtime = CollectionRuntime(
        settings=get_settings(),
        database=lambda: db,
        redis=lambda: redis,
        evidence=lambda: store,
        connectors=lambda: registry,
        requeue=requeued,
    )
    return runtime, requeued
