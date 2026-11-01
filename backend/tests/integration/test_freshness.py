from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.freshness import Freshness, offer_freshness
from pricing_assistant.core.db import Database
from pricing_assistant.sources.api import FetchErrorClass, FetchFailure
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A
from .test_collection_pipeline import envelope

pytestmark = pytest.mark.integration


async def test_observation_ages_out_and_failed_fetch_keeps_last_valid_price(
    db: Database, redis_client: Redis
) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, quota=600)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    connector = RecordingConnector()  # first call returns a default successful draft
    runtime, _ = await collection_runtime(db, redis_client, connector)
    await handle_fetch(runtime, envelope(offer))
    observed_at = datetime.now(UTC)

    async with db.tenant_session(TENANT_A) as session:
        fresh = (await offer_freshness(session, [offer], max_age_seconds=7200))[offer]
        later = (
            await offer_freshness(
                session, [offer], max_age_seconds=7200, now=observed_at + timedelta(hours=3)
            )
        )[offer]
    assert fresh.state is Freshness.FRESH
    assert later.state is Freshness.STALE
    assert later.age_seconds is not None
    assert later.age_seconds >= 3 * 3600 - 5

    await redis_client.flushdb()
    connector.results = [FetchFailure(FetchErrorClass.PARSE_FAILURE, "layout")]
    await handle_fetch(runtime, envelope(offer, window=datetime(2026, 10, 25, 9, tzinfo=UTC)))
    async with db.tenant_session(TENANT_A) as session:
        failed = (await offer_freshness(session, [offer], max_age_seconds=7200))[offer]
    assert failed.state is Freshness.FAILED
    assert failed.last_observed_at is not None  # last valid price kept with its original time
