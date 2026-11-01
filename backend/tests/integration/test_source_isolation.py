"""A source that fails every request must not delay other sources (spec: Source isolation)."""

from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.models import ObservationRow
from pricing_assistant.collection.scheduling import schedule_due
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import OutboxEventRow
from pricing_assistant.sources.api import (
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    OfferTarget,
)
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector, draft
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration


class PerSourceConnector(RecordingConnector):
    def __init__(self, failing_source: object) -> None:
        super().__init__()
        self.failing_source = failing_source

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult:
        self.calls.append(target)
        if target.source_id == self.failing_source:
            return FetchFailure(FetchErrorClass.NETWORK, "connection refused")
        return draft(target)


async def test_failing_source_does_not_delay_other_sources(
    db: Database, redis_client: Redis
) -> None:
    now = datetime.now(UTC)
    variant = await seed_variant(db, TENANT_A)
    down = await seed_source(db, TENANT_A, name="Down", quota=600)
    healthy = await seed_source(db, TENANT_A, name="Healthy", quota=600)
    for i in range(5):
        await seed_offer(
            db,
            TENANT_A,
            source_id=down,
            variant_id=variant,
            url=f"https://www.lioncomputer.com/d{i}",
            due=now - timedelta(seconds=5),
        )
    healthy_offer = await seed_offer(
        db,
        TENANT_A,
        source_id=healthy,
        variant_id=variant,
        url="https://www.lioncomputer.com/h",
        due=now - timedelta(seconds=5),
    )

    assert await schedule_due(db, now=now) == 6
    async with db.tenant_session(TENANT_A) as session:
        requests = (
            await session.scalars(select(OutboxEventRow).order_by(OutboxEventRow.occurred_at))
        ).all()
    connector = PerSourceConnector(down)
    runtime, requeued = await collection_runtime(db, redis_client, connector)

    for event in requests:  # failing source's requests are processed first
        await redis_client.flushdb()
        await handle_fetch(runtime, event.envelope())

    async with db.tenant_session(TENANT_A) as session:
        healthy_observations = (
            await session.scalars(
                select(ObservationRow).where(ObservationRow.tracked_offer_id == healthy_offer)
            )
        ).all()
    assert len(healthy_observations) == 1
    assert len(requeued.items) == 5  # down source retried later with backoff, not inline
    assert all(delay >= 30_000 for _, delay in requeued.items)
