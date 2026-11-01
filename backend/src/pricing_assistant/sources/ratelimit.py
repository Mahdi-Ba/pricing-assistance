"""Per-source request quotas and per-user re-check budgets in Redis (design D5, task 4.5).

The source limiter is a sliding-window log evaluated atomically in Lua, so no 60-second
window ever holds more than ``quota_per_minute`` requests across all workers. Requests are also
spaced at least ``60 / quota`` seconds apart (polite, even load). A source may be paused, for
example after a ``Retry-After`` response; while paused no request is admitted.

Every caller — scheduled fetches, re-checks and qualification runs — must acquire a slot
before sending a request. A denied caller gets the wait time and retries later; nothing is
dropped.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

WINDOW_MS = 60_000
TEHRAN = ZoneInfo("Asia/Tehran")

# KEYS[1] window zset, KEYS[2] pause key, KEYS[3] last-grant key
# ARGV[1] limit, ARGV[2] min spacing ms, ARGV[3] now ms (or -1 to use Redis TIME), ARGV[4] member
_ACQUIRE = """
local now = tonumber(ARGV[3])
if now < 0 then
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end
local paused_ttl = redis.call('PTTL', KEYS[2])
if paused_ttl > 0 then
  return {0, paused_ttl, 1}
end
local limit = tonumber(ARGV[1])
local spacing = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60000)
local last = tonumber(redis.call('GET', KEYS[3]) or '-1')
if last >= 0 and now - last < spacing then
  return {0, spacing - (now - last), 0}
end
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return {0, tonumber(oldest[2]) + 60000 - now, 0}
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], 61000)
redis.call('SET', KEYS[3], now, 'PX', 61000)
return {1, 0, 0}
"""


@dataclass(frozen=True, slots=True)
class Admission:
    granted: bool
    retry_after_ms: int = 0
    paused: bool = False


class SourceRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_ACQUIRE)

    @staticmethod
    def _keys(tenant_id: uuid.UUID, source_id: uuid.UUID) -> list[str]:
        base = f"pa:quota:{tenant_id}:{source_id}"
        return [f"{base}:window", f"{base}:pause", f"{base}:last"]

    async def acquire(
        self,
        tenant_id: uuid.UUID,
        source_id: uuid.UUID,
        quota_per_minute: int,
        *,
        now_ms: int | None = None,
    ) -> Admission:
        if quota_per_minute <= 0:
            return Admission(granted=False, retry_after_ms=WINDOW_MS)
        spacing = WINDOW_MS // quota_per_minute
        granted, wait, paused = await self._script(
            keys=self._keys(tenant_id, source_id),
            args=[quota_per_minute, spacing, -1 if now_ms is None else now_ms, uuid.uuid4().hex],
        )
        return Admission(
            granted=bool(granted), retry_after_ms=max(0, int(wait)), paused=bool(paused)
        )

    async def pause(self, tenant_id: uuid.UUID, source_id: uuid.UUID, seconds: int) -> None:
        """Stop admitting requests for ``seconds`` (e.g. honouring ``Retry-After``)."""
        _, pause_key, _ = self._keys(tenant_id, source_id)
        await self._redis.set(pause_key, "1", px=max(1, seconds) * 1000)

    async def paused_for_ms(self, tenant_id: uuid.UUID, source_id: uuid.UUID) -> int:
        _, pause_key, _ = self._keys(tenant_id, source_id)
        ttl = int(await self._redis.pttl(pause_key))
        return max(0, ttl)


class RecheckBudget:
    """Daily on-demand re-check allowance per expert (Tehran calendar day)."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _key(tenant_id: uuid.UUID, user: str, day: str) -> str:
        return f"pa:recheck:{tenant_id}:{user}:{day}"

    @staticmethod
    def today(now: datetime | None = None) -> str:
        return (now or datetime.now(UTC)).astimezone(TEHRAN).date().isoformat()

    async def try_consume(
        self, tenant_id: uuid.UUID, user: str, daily_limit: int, *, now: datetime | None = None
    ) -> tuple[bool, int]:
        """Consume one re-check. Returns (allowed, remaining)."""
        key = self._key(tenant_id, user, self.today(now))
        used = int(await self._redis.incr(key))
        if used == 1:
            await self._redis.expire(key, 2 * 86_400)
        if used > daily_limit:
            await self._redis.decr(key)
            return False, 0
        return True, daily_limit - used

    async def refund(self, tenant_id: uuid.UUID, user: str, *, now: datetime | None = None) -> None:
        """Give back a re-check that was refused later (e.g. by the source quota)."""
        key = self._key(tenant_id, user, self.today(now))
        if int(await self._redis.decr(key)) < 0:
            await self._redis.set(key, 0)
