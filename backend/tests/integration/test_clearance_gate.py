import uuid

import pytest
from redis.asyncio import Redis

from pricing_assistant.core.crypto import SecretBox
from pricing_assistant.core.db import Database
from pricing_assistant.core.settings import get_settings
from pricing_assistant.sources.connector import FetchErrorClass, FetchFailure, ObservationDraft
from pricing_assistant.sources.models import SourceStatus
from pricing_assistant.sources.ratelimit import SourceRateLimiter
from pricing_assistant.sources.runtime import prepare_fetch, run_fetch
from tests.support.fakes import FixedRegistry, RecordingConnector
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

BOX = SecretBox.from_setting(get_settings().secret_encryption_keys)


async def _fetch(
    db: Database, redis: Redis, offer_id: uuid.UUID, connector: RecordingConnector
) -> object:
    async with db.tenant_session(TENANT_A) as session:
        prepared = await prepare_fetch(
            session,
            tenant_id=TENANT_A,
            tracked_offer_id=offer_id,
            box=BOX,
            user_agent="test",
            timeout_seconds=5,
        )
    return await run_fetch(
        prepared, limiter=SourceRateLimiter(redis), connectors=FixedRegistry(connector)
    )


@pytest.mark.parametrize(
    ("status", "cleared"),
    [
        (SourceStatus.APPROVED, False),
        (SourceStatus.CANDIDATE, True),
        (SourceStatus.SUSPENDED, True),
        (SourceStatus.REJECTED, True),
    ],
)
async def test_source_without_clearance_or_collectable_status_sends_no_request(
    db: Database, redis_client: Redis, status: SourceStatus, cleared: bool
) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, status=status, cleared=cleared)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    connector = RecordingConnector()

    result = await _fetch(db, redis_client, offer, connector)

    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.CLEARANCE_MISSING
    assert connector.calls == []


async def test_cleared_source_is_fetched(db: Database, redis_client: Redis) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, status=SourceStatus.UNDER_EVALUATION)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    connector = RecordingConnector()

    result = await _fetch(db, redis_client, offer, connector)

    assert isinstance(result, ObservationDraft)
    assert [t.tracked_offer_id for t in connector.calls] == [offer]


async def test_blocked_response_pauses_the_source(db: Database, redis_client: Redis) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, quota=60)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    blocked = FetchFailure(FetchErrorClass.BLOCKED, "429", http_status=429, retry_after_seconds=600)
    connector = RecordingConnector(blocked)

    first = await _fetch(db, redis_client, offer, connector)
    second = await _fetch(db, redis_client, offer, connector)

    assert isinstance(first, FetchFailure)
    assert first.error_class is FetchErrorClass.BLOCKED
    assert isinstance(second, FetchFailure)
    assert second.error_class is FetchErrorClass.QUOTA_EXHAUSTED
    assert second.retry_after_seconds is not None
    assert second.retry_after_seconds > 590
    assert len(connector.calls) == 1  # no retry and no alternative route while paused
