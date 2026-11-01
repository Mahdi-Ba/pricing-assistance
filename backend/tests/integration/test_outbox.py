from typing import ClassVar

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import SYSTEM_ACTOR, AuditEventRow, record
from pricing_assistant.core.consumer import consume, idempotent_consumer
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import DomainEvent, EventEnvelope, OutboxEventRow, publish
from pricing_assistant.core.outbox import OutboxRelay

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration


class SampleHappened(DomainEvent):
    event_type: ClassVar[str] = "test.sample_happened"
    value: int


class Boom(Exception):
    pass


async def _audit_handler(session: AsyncSession, envelope: EventEnvelope) -> None:
    event = envelope.decode(SampleHappened)
    await record(
        session,
        tenant_id=envelope.tenant_id,
        actor=SYSTEM_ACTOR,
        action="test.handled",
        target_type="sample",
        target_id=str(event.value),
    )


async def _count_handled(db: Database) -> int:
    async with db.tenant_session(TENANT_A) as session:
        count = await session.scalar(
            select(func.count()).where(AuditEventRow.action == "test.handled")
        )
    return int(count or 0)


async def test_committed_event_is_dispatched_exactly_once_by_relay(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        published = await publish(session, tenant_id=TENANT_A, event=SampleHappened(value=7))
    sent: list[EventEnvelope] = []
    relay = OutboxRelay(db, sent.append)

    assert await relay.relay_once() == 1
    assert await relay.relay_once() == 0
    assert [e.event_id for e in sent] == [published.event_id]
    assert sent[0].decode(SampleHappened).value == 7


async def test_rolled_back_transaction_publishes_nothing(db: Database) -> None:
    with pytest.raises(Boom):
        async with db.tenant_session(TENANT_A) as session:
            await publish(session, tenant_id=TENANT_A, event=SampleHappened(value=1))
            raise Boom
    sent: list[EventEnvelope] = []

    assert await OutboxRelay(db, sent.append).relay_once() == 0
    assert sent == []


async def test_failed_dispatch_keeps_event_pending(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        await publish(session, tenant_id=TENANT_A, event=SampleHappened(value=2))

    def failing(_envelope: EventEnvelope) -> None:
        raise ConnectionError("broker down")

    with pytest.raises(ConnectionError):
        await OutboxRelay(db, failing).relay_once()
    sent: list[EventEnvelope] = []
    assert await OutboxRelay(db, sent.append).relay_once() == 1


async def test_duplicate_delivery_is_processed_once(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        envelope = await publish(session, tenant_id=TENANT_A, event=SampleHappened(value=3))
    actor = idempotent_consumer("test.audit_consumer", lambda: db)(_audit_handler)
    message = envelope.model_dump(mode="json")

    assert await actor(message) is True
    assert await actor(message) is False
    assert await _count_handled(db) == 1


async def test_failing_handler_does_not_mark_event_processed(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        envelope = await publish(session, tenant_id=TENANT_A, event=SampleHappened(value=4))

    async def flaky(_session: AsyncSession, _envelope: EventEnvelope) -> None:
        raise Boom

    with pytest.raises(Boom):
        await consume(db, "test.flaky", envelope, flaky)
    assert await consume(db, "test.flaky", envelope, _audit_handler) is True


async def test_outbox_payload_cannot_be_modified_by_app_role(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        await publish(session, tenant_id=TENANT_A, event=SampleHappened(value=5))
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            row = await session.scalar(select(OutboxEventRow))
            assert row is not None
            row.payload = {"value": 999}


async def test_relay_handles_each_tenant_in_its_own_scope(db: Database) -> None:
    for tenant in (TENANT_A, TENANT_B):
        async with db.tenant_session(tenant) as session:
            await publish(session, tenant_id=tenant, event=SampleHappened(value=1))
    sent: list[EventEnvelope] = []
    assert await OutboxRelay(db, sent.append).relay_once() == 2
    assert {e.tenant_id for e in sent} == {TENANT_A, TENANT_B}
