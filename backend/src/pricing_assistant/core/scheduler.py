"""Single-active scheduler with leader election through a PostgreSQL advisory lock.

Several scheduler replicas may run; only the one holding the session-level advisory lock runs
jobs. If its database connection drops, PostgreSQL releases the lock and a standby takes over.
"""

import asyncio
import contextlib
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from pricing_assistant.core.logging import get_logger
from pricing_assistant.core.metrics import (
    SCHEDULER_HEARTBEAT,
    SCHEDULER_IS_LEADER,
    SCHEDULER_JOB_RUNS,
)

log = get_logger(__name__)


def advisory_key(name: str) -> int:
    """Stable signed 64-bit key for ``pg_try_advisory_lock``."""
    digest = hashlib.sha256(name.encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class LeaderLock:
    def __init__(self, engine: AsyncEngine, name: str) -> None:
        self._engine = engine
        self._key = advisory_key(name)
        self._conn: AsyncConnection | None = None

    @property
    def held(self) -> bool:
        return self._conn is not None

    async def try_acquire(self) -> bool:
        if self._conn is not None:
            return True
        conn = await self._engine.connect()
        try:
            acquired = bool(
                await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": self._key})
            )
            await conn.commit()
        except Exception:
            await conn.close()
            raise
        if acquired:
            self._conn = conn
        else:
            await conn.close()
        return acquired

    async def verify(self) -> bool:
        """Check the lock connection is alive; drop leadership if it is not."""
        if self._conn is None:
            return False
        try:
            await self._conn.scalar(text("SELECT 1"))
            await self._conn.commit()
        except Exception:
            log.warning("scheduler.leader_lost")
            await self._discard(invalidate=True)
            return False
        return True

    async def release(self) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": self._key})
            await self._conn.commit()
        finally:
            await self._discard()

    async def _discard(self, *, invalidate: bool = False) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                if invalidate:
                    await conn.invalidate()
                await conn.close()
            except Exception:
                log.debug("scheduler.lock_connection_close_failed")


Job = Callable[[], Awaitable[object]]


@dataclass
class ScheduledJob:
    name: str
    interval_seconds: float
    run: Job
    last_run: float = field(default=float("-inf"))


class Scheduler:
    def __init__(self, lock: LeaderLock, jobs: list[ScheduledJob], *, instance: str) -> None:
        self._lock = lock
        self._jobs = jobs
        self._instance = instance

    @property
    def is_leader(self) -> bool:
        return self._lock.held

    async def tick(self, now: float | None = None) -> list[str]:
        """One loop iteration: keep or acquire leadership, then run due jobs. Returns job names."""
        now = time.monotonic() if now is None else now
        SCHEDULER_HEARTBEAT.labels(self._instance).set(time.time())
        leader = await self._lock.verify() or await self._lock.try_acquire()
        SCHEDULER_IS_LEADER.labels(self._instance).set(1 if leader else 0)
        if not leader:
            return []
        ran: list[str] = []
        for job in self._jobs:
            if now - job.last_run < job.interval_seconds:
                continue
            job.last_run = now
            try:
                await job.run()
                SCHEDULER_JOB_RUNS.labels(job.name, "ok").inc()
            except Exception:
                SCHEDULER_JOB_RUNS.labels(job.name, "error").inc()
                log.exception("scheduler.job_failed", job=job.name)
            ran.append(job.name)
        return ran

    async def run_forever(self, stop: asyncio.Event, *, poll_seconds: float = 1.0) -> None:
        log.info("scheduler.started", instance=self._instance)
        try:
            while not stop.is_set():
                await self.tick()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        await self._lock.release()
        SCHEDULER_IS_LEADER.labels(self._instance).set(0)
        log.info("scheduler.stopped", instance=self._instance)
