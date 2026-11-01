import asyncio
import itertools
import uuid
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis

from pricing_assistant.sources.ratelimit import RecheckBudget, SourceRateLimiter

pytestmark = pytest.mark.integration

TENANT = uuid.uuid4()


async def test_60_rpm_quota_under_200_due_offers_never_exceeds_and_drops_nothing(
    redis_client: Redis,
) -> None:
    limiter = SourceRateLimiter(redis_client)
    source = uuid.uuid4()
    pending = list(range(200))
    granted_at: list[int] = []
    now = 0
    while pending and now < 400_000:
        batch, pending = pending[:10], pending[10:]  # ten workers race for slots each tick
        results = await asyncio.gather(
            *(limiter.acquire(TENANT, source, 60, now_ms=now) for _ in batch)
        )
        for item, admission in zip(batch, results, strict=True):
            if admission.granted:
                granted_at.append(now)
            else:
                assert admission.retry_after_ms > 0
                pending.append(item)  # delayed, not dropped
        now += 250

    assert len(granted_at) == 200
    for start in granted_at:
        in_window = sum(1 for t in granted_at if start <= t < start + 60_000)
        assert in_window <= 60
    gaps = [b - a for a, b in itertools.pairwise(granted_at)]
    assert min(gaps) >= 1_000


async def test_window_caps_requests_when_spacing_alone_would_not(redis_client: Redis) -> None:
    limiter = SourceRateLimiter(redis_client)
    source = uuid.uuid4()
    # quota 7/min → spacing floor(60000/7) = 8571 ms, so seven grants end at 51426 ms and an
    # eighth request at 59997 ms satisfies spacing but would be the 8th in the window.
    times = [i * 8_571 for i in range(7)]
    assert all([(await limiter.acquire(TENANT, source, 7, now_ms=t)).granted for t in times])
    eighth = await limiter.acquire(TENANT, source, 7, now_ms=59_997)
    assert eighth.granted is False
    assert eighth.retry_after_ms == 3
    assert (await limiter.acquire(TENANT, source, 7, now_ms=60_000)).granted


async def test_paused_source_admits_nothing(redis_client: Redis) -> None:
    limiter = SourceRateLimiter(redis_client)
    source = uuid.uuid4()
    await limiter.pause(TENANT, source, 600)
    admission = await limiter.acquire(TENANT, source, 60)
    assert admission.granted is False
    assert admission.paused is True
    assert 590_000 < admission.retry_after_ms <= 600_000
    assert await limiter.paused_for_ms(TENANT, source) > 0


async def test_recheck_budget_per_user_per_day(redis_client: Redis) -> None:
    budget = RecheckBudget(redis_client)
    day1 = datetime(2026, 10, 25, 10, tzinfo=UTC)
    results = [await budget.try_consume(TENANT, "expert-1", 3, now=day1) for _ in range(4)]
    assert results == [(True, 2), (True, 1), (True, 0), (False, 0)]
    assert await budget.try_consume(TENANT, "expert-2", 3, now=day1) == (True, 2)
    await budget.refund(TENANT, "expert-1", now=day1)
    assert await budget.try_consume(TENANT, "expert-1", 3, now=day1) == (True, 0)
    # 21:00 UTC is already the next day in Tehran (UTC+3:30).
    next_day = datetime(2026, 10, 25, 21, tzinfo=UTC)
    assert await budget.try_consume(TENANT, "expert-1", 3, now=next_day) == (True, 2)
