"""Outbox → Dramatiq → idempotent consumer, through a real worker and event-loop thread."""

from collections.abc import Iterator

import dramatiq
import pytest
from dramatiq.asyncio import get_event_loop_thread
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware.asyncio import AsyncIO
from sqlalchemy import func, select

from pricing_assistant.audit.api import AuditEventRow
from pricing_assistant.core.broker import broker_dispatcher
from pricing_assistant.core.consumer import idempotent_consumer
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import publish
from pricing_assistant.core.outbox import OutboxRelay, Subscriptions
from pricing_assistant.core.runtime import LazyDatabase
from pricing_assistant.core.settings import get_settings

from .conftest import TENANT_A
from .test_outbox import SampleHappened, _audit_handler

pytestmark = pytest.mark.integration


@pytest.fixture
def broker() -> Iterator[StubBroker]:
    stub = StubBroker()
    stub.add_middleware(AsyncIO())
    stub.emit_after("process_boot")
    dramatiq.set_broker(stub)
    yield stub
    stub.flush_all()
    stub.close()


async def test_event_reaches_actor_once_despite_redelivery(
    db: Database, broker: StubBroker
) -> None:
    worker_db = LazyDatabase(get_settings().database_app_url, pool_size=2)
    handler = idempotent_consumer("test.worker_consumer", worker_db)(_audit_handler)
    actor = dramatiq.actor(actor_name="test.worker_consumer", broker=broker, max_retries=0)(handler)
    subscriptions = Subscriptions()
    subscriptions.subscribe(SampleHappened.event_type, actor.actor_name)
    dispatch = broker_dispatcher(broker, subscriptions)

    async with db.tenant_session(TENANT_A) as session:
        envelope = await publish(session, tenant_id=TENANT_A, event=SampleHappened(value=11))
    assert await OutboxRelay(db, dispatch).relay_once() == 1
    dispatch(envelope)  # simulate an at-least-once redelivery

    worker = dramatiq.Worker(broker, worker_timeout=50)
    worker.start()
    try:
        broker.join(actor.queue_name, fail_fast=True)
        worker.join()
        get_event_loop_thread().run_coroutine(worker_db.dispose())  # type: ignore[union-attr]
    finally:
        worker.stop()

    async with db.tenant_session(TENANT_A) as session:
        handled = await session.scalar(
            select(func.count()).where(AuditEventRow.action == "test.handled")
        )
    assert handled == 1
