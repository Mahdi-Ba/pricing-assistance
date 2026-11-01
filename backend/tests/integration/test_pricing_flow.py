import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from pricing_assistant.audit.api import list_events
from pricing_assistant.collection.evidence import EvidenceStore
from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.retention import purge
from pricing_assistant.core import tenant_settings
from pricing_assistant.core.db import Database
from pricing_assistant.core.settings import get_settings
from pricing_assistant.pricing.consumers import RecomputeScheduler
from pricing_assistant.pricing.models import RecommendationRow
from pricing_assistant.pricing.service import confirm_outlier, current_recommendation, replay
from pricing_assistant.sources.api import (
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    OfferTarget,
    TrackedOfferRow,
)
from tests.support.api import api_client, auth
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector, draft
from tests.support.pricing import Captured, PricingHarness, confirm_all_matches, default_rule
from tests.support.seed import ADMIN, seed_cost, seed_offer, seed_source, seed_variant

from .conftest import TENANT_A
from .test_collection_pipeline import envelope

pytestmark = pytest.mark.integration

TITLE = "SSD سامسونگ 990 PRO 1TB"


class PricedConnector(RecordingConnector):
    """Returns a price per tracked offer; ``down`` sources always fail."""

    def __init__(self, prices: dict[uuid.UUID, int], down: set[uuid.UUID] | None = None) -> None:
        super().__init__()
        self.prices = prices
        self.down = down or set()

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult:
        self.calls.append(target)
        if target.source_id in self.down:
            return FetchFailure(FetchErrorClass.NETWORK, "down")
        return draft(
            target,
            price_rial=self.prices[target.tracked_offer_id],
            seller=f"shop-{target.tracked_offer_id.hex[:4]}",
            title=TITLE,
        )


async def _setup(
    db: Database, redis: Redis, prices: list[int], **source: object
) -> tuple[PricingHarness, uuid.UUID, list[uuid.UUID], PricedConnector]:
    variant = await seed_variant(db, TENANT_A, price_rial=89_000_000)
    await seed_cost(db, TENANT_A, variant, 75_600_000)  # floor 84,000,000 at 10%
    await default_rule(db, TENANT_A, rounding_step_rial=100_000)
    offers = []
    for i, _ in enumerate(prices):
        src = await seed_source(db, TENANT_A, name=f"S{i}", quota=600, **source)  # type: ignore[arg-type]
        offers.append(
            await seed_offer(
                db,
                TENANT_A,
                source_id=src,
                variant_id=variant,
                url=f"https://www.lioncomputer.com/p{i}",
            )
        )
    connector = PricedConnector(dict(zip(offers, prices, strict=True)))
    runtime, _ = await collection_runtime(db, redis, connector)
    return PricingHarness(db, redis, TENANT_A, collection=runtime), variant, offers, connector


async def _fetch_all(harness: PricingHarness, offers: list[uuid.UUID], window: datetime) -> None:
    for offer in offers:
        await harness.redis.flushdb()
        assert harness.collection is not None
        await handle_fetch(harness.collection, envelope(offer, window=window))
    await harness.settle()


async def test_observation_to_recommendation_end_to_end(db: Database, redis_client: Redis) -> None:
    harness, variant, offers, _ = await _setup(db, redis_client, [86_000_000])
    await _fetch_all(harness, offers, datetime.now(UTC))
    async with db.tenant_session(TENANT_A) as session:
        pending = await current_recommendation(session, variant)
    assert pending is not None
    assert (pending.outcome, pending.reason_code) == ("insufficient_data", "pending_review")

    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    async with db.tenant_session(TENANT_A) as session:
        rec = await current_recommendation(session, variant)
    assert rec is not None
    assert (rec.outcome, rec.suggested_price_rial, rec.reason_code) == (
        "decrease",
        85_500_000,
        "above_market",
    )
    assert rec.floor_rial == 84_000_000
    assert "۸٬۶۰۰٬۰۰۰ تومان" in rec.explanation
    assert rec.cost_record_id is not None
    assert rec.rule_version_ids
    assert rec.observation_ids
    assert rec.match_version_ids


async def test_burst_of_observations_yields_one_recompute(
    db: Database, redis_client: Redis
) -> None:
    captured = Captured()
    scheduler = RecomputeScheduler(lambda: redis_client, captured)
    variant = uuid.uuid4()
    for _ in range(10):
        await scheduler.request(TENANT_A, [variant], correlation_id="burst")
    assert len(captured.messages) == 1
    assert captured.messages[0][1] == 5_000


async def test_new_observation_supersedes_previous_recommendation(
    db: Database, redis_client: Redis
) -> None:
    harness, variant, offers, connector = await _setup(db, redis_client, [86_000_000])
    await _fetch_all(harness, offers, datetime.now(UTC) - timedelta(minutes=1))
    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    async with db.tenant_session(TENANT_A) as session:
        first = await current_recommendation(session, variant)
    assert first is not None

    connector.prices[offers[0]] = 85_000_000
    await _fetch_all(harness, offers, datetime.now(UTC))
    async with db.tenant_session(TENANT_A) as session:
        second = await current_recommendation(session, variant)
        old = await session.get(RecommendationRow, first.id)
    assert second is not None
    assert old is not None
    assert (second.market_ref_rial, second.suggested_price_rial) == (85_000_000, 84_500_000)
    assert old.superseded_by == second.id


async def test_replay_returns_identical_output_and_reports_purged_inputs(
    db: Database, maintenance_db: Database, redis_client: Redis
) -> None:
    harness, variant, offers, _ = await _setup(db, redis_client, [86_000_000])
    await _fetch_all(harness, offers, datetime.now(UTC))
    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    async with db.tenant_session(TENANT_A) as session:
        rec = await current_recommendation(session, variant)
        assert rec is not None
        result = await replay(session, rec.id)
    assert result.identical
    assert not result.inputs_purged

    async with db.tenant_session(TENANT_A) as session:
        await tenant_settings.update(session, TENANT_A, {"observation_retention_days": 30}, "admin")
    await purge(
        maintenance_db, EvidenceStore(get_settings()), now=datetime.now(UTC) + timedelta(days=31)
    )
    async with db.tenant_session(TENANT_A) as session:
        kept = await session.get(RecommendationRow, rec.id)
        after = await replay(session, rec.id)
    assert kept is not None  # recommendations are kept, not deleted
    assert after.inputs_purged
    assert not after.identical


async def test_outlier_excluded_until_expert_confirms(db: Database, redis_client: Redis) -> None:
    harness, variant, offers, connector = await _setup(
        db, redis_client, [86_000_000, 87_000_000, 80_000_000]
    )
    await _fetch_all(harness, offers, datetime.now(UTC))
    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    async with db.tenant_session(TENANT_A) as session:
        rec = await current_recommendation(session, variant)
    assert rec is not None
    assert rec.market_ref_rial == 80_000_000  # 80M is 7% below the others' median: not an outlier
    # Make it an outlier: 70M is 19% below the median of the others.
    connector.prices[offers[2]] = 70_000_000
    await _fetch_all(harness, [offers[2]], datetime.now(UTC) + timedelta(seconds=1))
    async with db.tenant_session(TENANT_A) as session:
        rec = await current_recommendation(session, variant)
    assert rec is not None
    assert rec.market_ref_rial == 86_000_000
    [outlier] = rec.excluded_outlier_ids

    async with db.tenant_session(TENANT_A) as session:
        await confirm_outlier(
            session, tenant_id=TENANT_A, actor=ADMIN, observation_id=outlier, reason="حراج واقعی"
        )
    await harness.settle()
    async with db.tenant_session(TENANT_A) as session:
        rec = await current_recommendation(session, variant)
        audit = await list_events(session, action="pricing.outlier.confirmed")
    assert rec is not None
    assert rec.outcome == "floor_conflict"  # 70M is the market now, below the 84M floor
    assert rec.market_ref_rial == 70_000_000
    assert audit[0].reason == "حراج واقعی"


async def test_one_source_down_recommendations_still_computed(
    db: Database, redis_client: Redis
) -> None:
    harness, variant, offers, connector = await _setup(db, redis_client, [86_000_000, 87_000_000])
    async with db.tenant_session(TENANT_A) as session:
        tracked = await session.get(TrackedOfferRow, offers[1])
    assert tracked is not None
    down_source = tracked.source_id
    connector.down = {down_source}
    await _fetch_all(harness, offers, datetime.now(UTC))
    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    async with db.tenant_session(TENANT_A) as session:
        rec = await current_recommendation(session, variant)
    assert rec is not None
    assert (rec.outcome, rec.market_ref_rial, rec.qualifying_count) == ("decrease", 86_000_000, 1)


async def test_pricing_api_replay_and_outlier_endpoints(db: Database, redis_client: Redis) -> None:
    harness, variant, offers, _ = await _setup(
        db, redis_client, [86_000_000, 87_000_000, 70_000_000]
    )
    await _fetch_all(harness, offers, datetime.now(UTC))
    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    expert = auth(TENANT_A, "expert", username="pilot-expert")
    async with api_client(db) as client:
        current = (await client.get(f"/variants/{variant}/recommendation", headers=expert)).json()
        replayed = (
            await client.post(f"/recommendations/{current['id']}/replay", headers=expert)
        ).json()
        [outlier] = current["excluded_outlier_ids"]
        missing_reason = await client.post(
            f"/observations/{outlier}/outlier-confirmation", headers=expert, json={"reason": ""}
        )
        confirmed = await client.post(
            f"/observations/{outlier}/outlier-confirmation", headers=expert, json={"reason": "حراج"}
        )
        not_outlier = await client.post(
            f"/observations/{current['market_ref_observation_id']}/outlier-confirmation",
            headers=expert,
            json={"reason": "x"},
        )
    assert current["market_ref_rial"] == 86_000_000
    assert replayed == {
        "recommendation_id": current["id"],
        "identical": True,
        "inputs_purged": False,
        "stored": replayed["recomputed"],
        "recomputed": replayed["stored"],
    }
    assert missing_reason.status_code == 422
    assert confirmed.status_code == 201
    assert not_outlier.status_code == 409
