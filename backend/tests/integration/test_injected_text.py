"""Page content is data: an instruction inside a title changes nothing (spec: Untrusted page
content)."""

from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from pricing_assistant.audit.api import AuditEventRow
from pricing_assistant.catalog.rules import ProfitRuleVersionRow
from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.models import ObservationRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.models import ExtractionRuleVersionRow, SourceRow
from tests.contract.harness import replay_registry
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector
from tests.support.fixtures import fixture_json
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A
from .test_collection_pipeline import envelope

pytestmark = pytest.mark.integration


async def test_instruction_in_page_is_stored_as_data_only(
    db: Database, redis_client: Redis
) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, quota=600)
    offer = await seed_offer(
        db,
        TENANT_A,
        source_id=source,
        variant_id=variant,
        url="https://www.lioncomputer.com/p/sellers",
    )
    async with db.tenant_session(TENANT_A) as session:
        session.add(
            ExtractionRuleVersionRow(
                id=new_id(),
                tenant_id=TENANT_A,
                source_id=source,
                version=1,
                config=fixture_json("generic/marketplace_rule.json"),
                state="active",
                origin="admin",
                created_by="seed",
            )
        )
    runtime, _ = await collection_runtime(db, redis_client, RecordingConnector())
    registry = replay_registry({"/p/sellers": "generic/marketplace_sellers.html"})
    runtime.connectors = lambda: registry  # real page connector over the recorded fixture

    async with db.tenant_session(TENANT_A) as session:
        before = {
            "audit": await session.scalar(select(func.count()).select_from(AuditEventRow)),
            "rules": await session.scalar(select(func.count()).select_from(ProfitRuleVersionRow)),
            "source": (await session.get(SourceRow, source)).status,  # type: ignore[union-attr]
        }

    await handle_fetch(runtime, envelope(offer, window=datetime(2026, 10, 25, 7, tzinfo=UTC)))

    async with db.tenant_session(TENANT_A) as session:
        rows = (
            await session.scalars(select(ObservationRow).order_by(ObservationRow.price_rial))
        ).all()
        after = {
            "audit": await session.scalar(select(func.count()).select_from(AuditEventRow)),
            "rules": await session.scalar(select(func.count()).select_from(ProfitRuleVersionRow)),
            "source": (await session.get(SourceRow, source)).status,  # type: ignore[union-attr]
        }
    injected = [r for r in rows if r.seller and "ignore previous instructions" in r.seller]
    assert len(injected) == 1
    assert injected[0].price_rial == 91_000_000  # the page's price, not "1"
    assert all(r.price_rial not in {1, 10} for r in rows)
    assert after == before  # no rule, source or audited state changed
