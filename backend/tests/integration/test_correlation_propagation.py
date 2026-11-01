"""One correlation ID follows a request through the API log, the outbox, a worker and audit."""

import json
from collections.abc import Iterator
from typing import Annotated

import dramatiq
import httpx
import pytest
from dramatiq.asyncio import get_event_loop_thread
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware.asyncio import AsyncIO
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.app import create_app
from pricing_assistant.audit.api import SYSTEM_ACTOR, list_events, record
from pricing_assistant.core.broker import broker_dispatcher
from pricing_assistant.core.consumer import idempotent_consumer
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope, publish
from pricing_assistant.core.logging import configure_logging, get_logger
from pricing_assistant.core.outbox import OutboxRelay, Subscriptions
from pricing_assistant.core.runtime import LazyDatabase
from pricing_assistant.core.settings import get_settings
from pricing_assistant.iam.api import ExpertPrincipal, actor_of
from tests.support.tokens import issue_token, make_validator

from .conftest import TENANT_A
from .test_outbox import SampleHappened

pytestmark = pytest.mark.integration

CORRELATION_ID = "corr-e2e-4f1c9a"


@pytest.fixture
def broker() -> Iterator[StubBroker]:
    stub = StubBroker()
    stub.add_middleware(AsyncIO())
    stub.emit_after("process_boot")
    dramatiq.set_broker(stub)
    yield stub
    stub.close()


async def _worker_handler(session: AsyncSession, envelope: EventEnvelope) -> None:
    get_logger("worker.test").info("test.worker_handled", event_id=str(envelope.event_id))
    await record(
        session,
        tenant_id=envelope.tenant_id,
        actor=SYSTEM_ACTOR,
        action="test.worker_handled",
        target_type="sample",
    )


async def test_correlation_id_reaches_api_log_worker_log_and_audit(
    db: Database, broker: StubBroker, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_logging(level="INFO", json=True, service="test")
    router = APIRouter()

    @router.post("/test/commands", status_code=202)
    async def command(
        principal: ExpertPrincipal, database: Annotated[Database, Depends(lambda: db)]
    ) -> dict[str, str]:
        async with database.tenant_session(principal.tenant_id) as session:
            await record(
                session,
                tenant_id=principal.tenant_id,
                actor=actor_of(principal),
                action="test.command",
                target_type="sample",
            )
            await publish(session, tenant_id=principal.tenant_id, event=SampleHappened(value=1))
        return {"status": "accepted"}

    app = create_app(database=db, token_validator=make_validator(), extra_routers=[router])
    token = issue_token(tenant_id=TENANT_A, roles=["expert"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/test/commands",
            headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": CORRELATION_ID},
        )
    assert response.status_code == 202
    assert response.headers["X-Correlation-ID"] == CORRELATION_ID

    worker_db = LazyDatabase(get_settings().database_app_url, pool_size=2)
    actor = dramatiq.actor(actor_name="test.correlated", broker=broker, max_retries=0)(
        idempotent_consumer("test.correlated", worker_db)(_worker_handler)
    )
    subscriptions = Subscriptions()
    subscriptions.subscribe(SampleHappened.event_type, actor.actor_name)
    assert await OutboxRelay(db, broker_dispatcher(broker, subscriptions)).relay_once() == 1
    worker = dramatiq.Worker(broker, worker_timeout=50)
    worker.start()
    try:
        broker.join(actor.queue_name, fail_fast=True)
        worker.join()
        get_event_loop_thread().run_coroutine(worker_db.dispose())  # type: ignore[union-attr]
    finally:
        worker.stop()

    logs = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    by_event = {entry["event"]: entry for entry in logs}
    assert by_event["http.request"]["correlation_id"] == CORRELATION_ID
    assert by_event["event.consumed"]["correlation_id"] == CORRELATION_ID
    assert by_event["test.worker_handled"]["correlation_id"] == CORRELATION_ID
    async with db.tenant_session(TENANT_A) as session:
        events = await list_events(session)
    assert {e.action: e.correlation_id for e in events} == {
        "test.command": CORRELATION_ID,
        "test.worker_handled": CORRELATION_ID,
    }
