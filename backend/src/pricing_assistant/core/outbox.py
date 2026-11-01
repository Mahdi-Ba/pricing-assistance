"""Outbox relay: moves committed events from ``outbox_event`` to the job queue.

Delivery is at-least-once. If the relay crashes after sending but before marking an event
dispatched, the event is sent again; consumers deduplicate by ``event_id``.
"""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select

from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope, OutboxEventRow
from pricing_assistant.core.logging import get_logger
from pricing_assistant.core.metrics import OUTBOX_LAG_SECONDS

Dispatcher = Callable[[EventEnvelope], None]
log = get_logger(__name__)


class Subscriptions:
    """Maps event types to the actors that consume them, and actors to their queues.

    Senders route by actor and queue name only, so a process (the scheduler, the API) can send
    to actors that are declared in another process (the workers).
    """

    def __init__(self) -> None:
        self._by_type: dict[str, list[str]] = defaultdict(list)
        self._queues: dict[str, str] = {}

    def register(self, actor_name: str, queue_name: str = "default") -> None:
        self._queues[actor_name] = queue_name

    def subscribe(self, event_type: str, actor_name: str, queue_name: str = "default") -> None:
        self._queues.setdefault(actor_name, queue_name)
        if actor_name not in self._by_type[event_type]:
            self._by_type[event_type].append(actor_name)

    def actors_for(self, event_type: str) -> list[str]:
        return list(self._by_type.get(event_type, ()))

    def queue_of(self, actor_name: str) -> str:
        return self._queues.get(actor_name, "default")


class OutboxRelay:
    def __init__(self, db: Database, dispatch: Dispatcher, *, batch_size: int = 200) -> None:
        self._db = db
        self._dispatch = dispatch
        self._batch_size = batch_size

    async def relay_once(self) -> int:
        """Dispatch pending events for every active tenant; return the number dispatched."""
        dispatched = 0
        lag = 0.0
        now = datetime.now(UTC)
        for tenant_id in await self._db.active_tenant_ids():
            async with self._db.tenant_session(tenant_id) as session:
                oldest = await session.scalar(
                    select(func.min(OutboxEventRow.occurred_at)).where(
                        OutboxEventRow.dispatched_at.is_(None)
                    )
                )
                if oldest is not None:
                    lag = max(lag, (now - oldest).total_seconds())
                rows = (
                    await session.scalars(
                        select(OutboxEventRow)
                        .where(OutboxEventRow.dispatched_at.is_(None))
                        .order_by(OutboxEventRow.occurred_at, OutboxEventRow.id)
                        .limit(self._batch_size)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                for row in rows:
                    row.attempts += 1
                    self._dispatch(row.envelope())
                    row.dispatched_at = datetime.now(UTC)
                    dispatched += 1
        OUTBOX_LAG_SECONDS.set(lag)
        if dispatched:
            log.info("outbox.dispatched", count=dispatched)
        return dispatched
