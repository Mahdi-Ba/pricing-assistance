"""Our own Torob listing is tracked as an own-channel source (task 6.8)."""

from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.models import ObservationRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.config import put_config
from pricing_assistant.sources.models import ExtractionRuleVersionRow
from tests.contract.harness import replay_registry
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector
from tests.support.fixtures import fixture_json
from tests.support.seed import ADMIN, seed_offer, seed_source, seed_variant

from .conftest import TENANT_A
from .test_collection_pipeline import envelope

pytestmark = pytest.mark.integration


async def test_channel_observation_is_flagged_and_limited_to_our_row(
    db: Database, redis_client: Redis
) -> None:
    variant = await seed_variant(db, TENANT_A)
    torob = await seed_source(db, TENANT_A, name="Torob pages", quota=600)
    offer = await seed_offer(
        db,
        TENANT_A,
        source_id=torob,
        variant_id=variant,
        url="https://www.lioncomputer.com/torob",
        own_channel=True,
    )
    async with db.tenant_session(TENANT_A) as session:
        session.add(
            ExtractionRuleVersionRow(
                id=new_id(),
                tenant_id=TENANT_A,
                source_id=torob,
                version=1,
                config=fixture_json("torob_page/rule.json"),
                state="active",
                origin="admin",
                created_by="seed",
            )
        )
        await put_config(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=torob,
            config={"own_seller_name": "فروشگاه ما"},
        )
    runtime, _ = await collection_runtime(db, redis_client, RecordingConnector())
    registry = replay_registry({"/torob": "torob_page/product.html"})
    runtime.connectors = lambda: registry

    await handle_fetch(runtime, envelope(offer, window=datetime(2026, 10, 25, 6, tzinfo=UTC)))

    async with db.tenant_session(TENANT_A) as session:
        rows = (await session.scalars(select(ObservationRow))).all()
    assert [(r.seller, r.price_rial, r.is_own_channel, r.is_own_store) for r in rows] == [
        ("فروشگاه ما", 88_900_000, True, False)
    ]
