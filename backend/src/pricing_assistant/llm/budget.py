"""Daily LLM token budget per tenant in Redis (task 8.6).

The budget is checked before a call and charged with the call's actual input + output tokens
afterwards, per Tehran calendar day. A single call can overshoot the remaining budget by at most
its own size; every later call that day is refused with :class:`BudgetExhausted`. A budget of
zero refuses every call.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

TEHRAN = ZoneInfo("Asia/Tehran")


class BudgetExhausted(Exception):
    """The tenant's daily LLM token budget is used up."""


class TokenBudget:
    def __init__(self, redis: Callable[[], Redis], daily_tokens: int) -> None:
        self._redis = redis  # resolved per call: the client belongs to the running event loop
        self.daily_tokens = daily_tokens

    @staticmethod
    def _key(tenant_id: uuid.UUID, now: datetime | None) -> str:
        day = (now or datetime.now(UTC)).astimezone(TEHRAN).date().isoformat()
        return f"pa:llm:tokens:{tenant_id}:{day}"

    async def used(self, tenant_id: uuid.UUID, *, now: datetime | None = None) -> int:
        return int(await self._redis().get(self._key(tenant_id, now)) or 0)

    async def check(self, tenant_id: uuid.UUID, *, now: datetime | None = None) -> None:
        if await self.used(tenant_id, now=now) >= self.daily_tokens:
            raise BudgetExhausted

    async def charge(
        self, tenant_id: uuid.UUID, tokens: int, *, now: datetime | None = None
    ) -> None:
        key = self._key(tenant_id, now)
        async with self._redis().pipeline(transaction=True) as pipe:
            pipe.incrby(key, max(0, tokens))
            pipe.expire(key, 2 * 86_400)
            await pipe.execute()
