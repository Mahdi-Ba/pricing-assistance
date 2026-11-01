import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select

from pricing_assistant.collection.events import FetchRequested
from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.collection.scheduling import schedule_due
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope, OutboxEventRow
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.api import (
    FetchErrorClass,
    FetchFailure,
    OfferTarget,
    SourceStatus,
    StockState,
    TrackedOfferRow,
)
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector, draft
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

WINDOW = datetime(2026, 10, 25, 8, 0, tzinfo=UTC)


def envelope(offer_id: uuid.UUID, *, window: datetime = WINDOW) -> EventEnvelope:
    request = FetchRequested(tracked_offer_id=offer_id, window_start=window, trigger="scheduled")
    return EventEnvelope(
        event_id=new_id(),
        type=request.event_type,
        version=1,
        tenant_id=TENANT_A,
        occurred_at=datetime.now(UTC),
        correlation_id="corr-collect-0001",
        payload=request.model_dump(mode="json"),
    )


async def _offer(db: Database, **kwargs: object) -> uuid.UUID:
    variant = await seed_variant(db, TENANT_A, sku=f"V-{uuid.uuid4().hex[:6]}")
    source = await seed_source(db, TENANT_A, name=f"S-{uuid.uuid4().hex[:6]}", quota=600)
    return await seed_offer(db, TENANT_A, source_id=source, variant_id=variant, **kwargs)  # type: ignore[arg-type]


async def _observations(db: Database, offer_id: uuid.UUID) -> list[ObservationRow]:
    async with db.tenant_session(TENANT_A) as session:
        rows = await session.scalars(
            select(ObservationRow)
            .where(ObservationRow.tracked_offer_id == offer_id)
            .order_by(ObservationRow.observed_at)
        )
        return list(rows.all())


async def _attempts(db: Database, offer_id: uuid.UUID) -> list[FetchAttemptRow]:
    async with db.tenant_session(TENANT_A) as session:
        rows = await session.scalars(
            select(FetchAttemptRow)
            .where(FetchAttemptRow.tracked_offer_id == offer_id)
            .order_by(FetchAttemptRow.attempt)
        )
        return list(rows.all())


async def test_scheduler_tick_publishes_due_offers_and_advances_by_tier(db: Database) -> None:
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    tier_a = await seed_variant(db, TENANT_A, sku="A-1", tier="A")
    tier_c = await seed_variant(db, TENANT_A, sku="C-1", tier="C")
    source = await seed_source(db, TENANT_A)
    suspended = await seed_source(db, TENANT_A, name="Suspended", status=SourceStatus.SUSPENDED)
    due_a = await seed_offer(
        db,
        TENANT_A,
        source_id=source,
        variant_id=tier_a,
        url="https://www.lioncomputer.com/a",
        due=now - timedelta(minutes=1),
    )
    due_c = await seed_offer(
        db,
        TENANT_A,
        source_id=source,
        variant_id=tier_c,
        url="https://www.lioncomputer.com/c",
        due=now - timedelta(hours=10),
    )
    await seed_offer(
        db,
        TENANT_A,
        source_id=source,
        variant_id=tier_a,
        url="https://www.lioncomputer.com/later",
        due=now + timedelta(minutes=5),
    )
    await seed_offer(
        db,
        TENANT_A,
        source_id=suspended,
        variant_id=tier_a,
        url="https://www.lioncomputer.com/s",
        due=now - timedelta(minutes=1),
    )

    assert await schedule_due(db, now=now) == 2
    assert await schedule_due(db, now=now) == 0

    async with db.tenant_session(TENANT_A) as session:
        offers = {o.id: o for o in (await session.scalars(select(TrackedOfferRow))).all()}
        events = (await session.scalars(select(OutboxEventRow))).all()
    assert offers[due_a].next_due_at == now - timedelta(minutes=1) + timedelta(seconds=900)
    assert offers[due_c].next_due_at == now + timedelta(seconds=21600)  # far behind: from now
    assert {e.payload["tracked_offer_id"] for e in events} == {str(due_a), str(due_c)}
    assert all(e.type == "fetch.requested" for e in events)


async def test_concurrent_ticks_schedule_each_offer_once(db: Database) -> None:
    now = datetime.now(UTC)
    for i in range(20):
        await _offer(db, url=f"https://www.lioncomputer.com/p/{i}", due=now - timedelta(seconds=1))
    counts = await asyncio.gather(*(schedule_due(db, now=now) for _ in range(4)))
    assert sum(counts) == 20


async def test_duplicate_trigger_executes_exactly_one_fetch(
    db: Database, redis_client: Redis
) -> None:
    offer = await _offer(db)
    connector = RecordingConnector()
    runtime, _ = await collection_runtime(db, redis_client, connector)

    first = await handle_fetch(runtime, envelope(offer))
    second = await handle_fetch(runtime, envelope(offer))

    assert first is not None
    assert second is None
    assert len(connector.calls) == 1
    assert len(await _observations(db, offer)) == 1


async def test_parse_failure_records_failure_and_no_observation(
    db: Database, redis_client: Redis
) -> None:
    offer = await _offer(db)
    connector = RecordingConnector(FetchFailure(FetchErrorClass.PARSE_FAILURE, "layout changed"))
    runtime, requeued = await collection_runtime(db, redis_client, connector)

    attempt = await handle_fetch(runtime, envelope(offer))

    assert attempt is not None
    assert (attempt.outcome, attempt.error_class, attempt.final) == (
        "failure",
        "parse_failure",
        True,
    )
    assert await _observations(db, offer) == []
    assert requeued.items == []
    async with db.tenant_session(TENANT_A) as session:
        types = (await session.scalars(select(OutboxEventRow.type))).all()
    assert "fetch.failed" in types
    assert "observation.recorded" not in types


async def test_explicit_out_of_stock_is_a_valid_observation(
    db: Database, redis_client: Redis
) -> None:
    offer = await _offer(db)
    async with db.tenant_session(TENANT_A) as session:
        row = await session.get(TrackedOfferRow, offer)
        assert row is not None
    connector = RecordingConnector()
    runtime, _ = await collection_runtime(db, redis_client, connector)

    async def fetch_oos(target: OfferTarget, ctx: object) -> object:
        connector.calls.append(target)
        return draft(target, price_rial=None, stock=StockState.OUT_OF_STOCK)

    connector.fetch = fetch_oos  # type: ignore[assignment,method-assign]

    await handle_fetch(runtime, envelope(offer))

    [observation] = await _observations(db, offer)
    assert (observation.stock_state, observation.validity, observation.price_rial) == (
        "out_of_stock",
        "valid",
        None,
    )
    assert len(observation.evidence_ids) == 2  # html + extracted json


async def test_transient_error_is_retried_with_backoff_then_recovers(
    db: Database, redis_client: Redis
) -> None:
    offer = await _offer(db)
    connector = RecordingConnector(FetchFailure(FetchErrorClass.HTTP_ERROR, "503", http_status=503))
    runtime, requeued = await collection_runtime(db, redis_client, connector)

    first = await handle_fetch(runtime, envelope(offer))
    assert first is not None
    assert first.final is False
    [(retry, delay)] = requeued.items
    assert 30_000 <= delay <= 60_000
    assert retry.payload["attempt"] == 2
    assert retry.causation_id is not None

    await redis_client.flushdb()  # the retry arrives ≥30 s later, after the request spacing
    second = await handle_fetch(runtime, retry)

    assert second is not None
    assert second.outcome == "success"
    assert [(a.attempt, a.outcome) for a in await _attempts(db, offer)] == [
        (1, "failure"),
        (2, "success"),
    ]
    assert len(await _observations(db, offer)) == 1


async def test_at_most_three_attempts(db: Database, redis_client: Redis) -> None:
    offer = await _offer(db)
    failures = [FetchFailure(FetchErrorClass.TIMEOUT, "slow") for _ in range(3)]
    connector = RecordingConnector(*failures)
    runtime, requeued = await collection_runtime(db, redis_client, connector)

    current = envelope(offer)
    for _ in range(3):
        await redis_client.flushdb()  # backoff delays exceed the source's request spacing
        await handle_fetch(runtime, current)
        if requeued.items:
            current = requeued.items.pop()[0]
    attempts = await _attempts(db, offer)
    assert [(a.attempt, a.final) for a in attempts] == [(1, False), (2, False), (3, True)]
    assert requeued.items == []


async def test_implausible_price_jump_is_flagged_suspect_unit(
    db: Database, redis_client: Redis
) -> None:
    offer = await _offer(db)
    async with db.tenant_session(TENANT_A) as session:
        target_row = await session.get(TrackedOfferRow, offer)
        assert target_row is not None

    connector = RecordingConnector()
    runtime, _ = await collection_runtime(db, redis_client, connector)
    await handle_fetch(runtime, envelope(offer))  # 86,000,000 baseline
    await redis_client.flushdb()  # time passes: the source's request spacing has elapsed

    async def fetch_low(target: OfferTarget, ctx: object) -> object:
        return draft(target, price_rial=8_600_000)

    connector.fetch = fetch_low  # type: ignore[assignment,method-assign]
    await handle_fetch(runtime, envelope(offer, window=WINDOW + timedelta(hours=1)))

    validity = [o.validity for o in await _observations(db, offer)]
    assert validity == ["valid", "suspect_unit"]


@pytest.mark.parametrize(("own_store", "own_channel"), [(True, False), (False, True)])
async def test_own_store_and_channel_observations_are_flagged(
    db: Database, redis_client: Redis, own_store: bool, own_channel: bool
) -> None:
    offer = await _offer(db, own_store=own_store, own_channel=own_channel)
    runtime, _ = await collection_runtime(db, redis_client, RecordingConnector())

    await handle_fetch(runtime, envelope(offer))

    [observation] = await _observations(db, offer)
    assert (observation.is_own_store, observation.is_own_channel) == (own_store, own_channel)
    async with db.tenant_session(TENANT_A) as session:
        event = await session.scalar(
            select(OutboxEventRow).where(OutboxEventRow.type == "observation.recorded")
        )
        count = await session.scalar(select(func.count()).select_from(ObservationRow))
    assert event is not None
    assert (event.payload["is_own_store"], event.payload["is_own_channel"]) == (
        own_store,
        own_channel,
    )
    assert count == 1
