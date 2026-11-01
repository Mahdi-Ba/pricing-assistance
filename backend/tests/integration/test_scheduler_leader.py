from collections.abc import AsyncIterator

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from pricing_assistant.core.db import create_engine
from pricing_assistant.core.scheduler import LeaderLock, ScheduledJob, Scheduler
from pricing_assistant.core.settings import get_settings

pytestmark = pytest.mark.integration

LOCK_NAME = "pricing-assistant.scheduler.test"


@pytest.fixture
async def engines(clean_db: None) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    a = create_engine(get_settings().database_app_url, pool_size=2)
    b = create_engine(get_settings().database_app_url, pool_size=2)
    yield a, b
    await a.dispose()
    await b.dispose()


def _scheduler(engine: AsyncEngine, instance: str, runs: list[str]) -> Scheduler:
    async def job() -> None:
        runs.append(instance)

    return Scheduler(
        LeaderLock(engine, LOCK_NAME),
        [ScheduledJob(name="outbox.relay", interval_seconds=1.0, run=job)],
        instance=instance,
    )


async def test_two_schedulers_elect_exactly_one_leader(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    runs: list[str] = []
    first, second = _scheduler(engines[0], "s1", runs), _scheduler(engines[1], "s2", runs)

    await first.tick(now=0)
    await second.tick(now=0)
    await first.tick(now=5)
    await second.tick(now=5)

    assert first.is_leader
    assert not second.is_leader
    assert runs == ["s1", "s1"]
    assert REGISTRY.get_sample_value("pa_scheduler_is_leader", {"instance": "s1"}) == 1
    assert REGISTRY.get_sample_value("pa_scheduler_is_leader", {"instance": "s2"}) == 0
    assert REGISTRY.get_sample_value("pa_scheduler_heartbeat_timestamp_seconds", {"instance": "s2"})
    await first.shutdown()
    await second.shutdown()
    assert REGISTRY.get_sample_value("pa_scheduler_is_leader", {"instance": "s1"}) == 0


async def test_standby_takes_over_when_leader_stops(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    runs: list[str] = []
    first_lock = LeaderLock(engines[0], LOCK_NAME)
    second = _scheduler(engines[1], "s2", runs)
    assert await first_lock.try_acquire()
    assert await second.tick(now=0) == []

    await first_lock.release()

    assert await second.tick(now=1) == ["outbox.relay"]
    assert second.is_leader
    await second.shutdown()


async def test_leadership_is_dropped_when_connection_dies(
    engines: tuple[AsyncEngine, AsyncEngine], owner_engine: Engine
) -> None:
    lock = LeaderLock(engines[0], LOCK_NAME)
    assert await lock.try_acquire()
    with owner_engine.begin() as conn:  # simulate the leader's database session dying
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_locks "
                "WHERE locktype = 'advisory' AND database = "
                "(SELECT oid FROM pg_database WHERE datname = current_database())"
            )
        )
    standby = LeaderLock(engines[1], LOCK_NAME)

    assert await lock.verify() is False
    assert await standby.try_acquire()
    await standby.release()
