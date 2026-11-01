import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope, OutboxEventRow
from pricing_assistant.sources.api import RecheckBudget, SourceRateLimiter
from tests.support.api import api_client, auth
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

EXPERT = auth(TENANT_A, "expert", username="pilot-expert")


async def _fetch_events(db: Database) -> list[OutboxEventRow]:
    async with db.tenant_session(TENANT_A) as session:
        rows = await session.scalars(
            select(OutboxEventRow).where(OutboxEventRow.type.like("fetch.requested%"))
        )
        return list(rows.all())


async def test_recheck_is_accepted_executed_and_tracked(db: Database, redis_client: Redis) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, quota=60)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    async with api_client(db) as client:
        accepted = await client.post(f"/tracked-offers/{offer}/recheck", headers=EXPERT)
        assert accepted.status_code == 202, accepted.text
        recheck_id = accepted.json()["id"]

        [event] = await _fetch_events(db)
        assert event.payload["slot_reserved"] is True
        assert event.payload["trigger"] == "recheck"
        connector = RecordingConnector()
        runtime, _ = await collection_runtime(db, redis_client, connector)
        await handle_fetch(runtime, EventEnvelope.model_validate(event.envelope().model_dump()))

        done = await client.get(f"/rechecks/{recheck_id}", headers=EXPERT)
    assert accepted.json()["status"] == "pending"
    assert done.json()["status"] == "completed"
    assert done.json()["fetch_attempt_id"] is not None
    assert len(connector.calls) == 1  # the reserved slot was not taken twice


async def test_recheck_refused_by_quota_sends_no_request(db: Database, redis_client: Redis) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, quota=1)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    assert (await SourceRateLimiter(redis_client).acquire(TENANT_A, source, 1)).granted

    async with api_client(db) as client:
        refused = await client.post(f"/tracked-offers/{offer}/recheck", headers=EXPERT)

    assert refused.status_code == 429
    body = refused.json()
    assert body["type"].endswith("source_quota_exhausted")
    assert "دوباره تلاش کنید" in body["message_fa"]
    assert int(refused.headers["Retry-After"]) > 50
    assert await _fetch_events(db) == []
    budget_key = f"pa:recheck:{TENANT_A}:pilot-expert:{RecheckBudget.today()}"
    assert await redis_client.get(budget_key) in (None, "0")  # refunded


async def test_daily_budget_is_enforced(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, quota=600)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    async with api_client(db) as client:
        await client.patch(
            "/settings", headers=auth(TENANT_A, "admin"), json={"recheck_daily_budget_per_user": 1}
        )
        first = await client.post(f"/tracked-offers/{offer}/recheck", headers=EXPERT)
        second = await client.post(f"/tracked-offers/{offer}/recheck", headers=EXPERT)
    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["type"].endswith("recheck_budget_exhausted")
