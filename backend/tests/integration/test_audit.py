import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from pricing_assistant.audit.api import AuditActor, list_events, record
from pricing_assistant.core.correlation import set_correlation_id
from pricing_assistant.core.db import Database

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration

ACTOR = AuditActor(subject="user-1", username="pilot-expert")


async def test_record_persists_event_with_correlation(db: Database) -> None:
    set_correlation_id("corr-audit-0001")
    async with db.tenant_session(TENANT_A) as session:
        await record(
            session,
            tenant_id=TENANT_A,
            actor=ACTOR,
            action="decision.recorded",
            target_type="recommendation",
            target_id="rec-1",
            after={"type": "accept", "reason": "below market"},
            reason="below market",
        )
    async with db.tenant_session(TENANT_A) as session:
        events = await list_events(session, action="decision.recorded")
    assert len(events) == 1
    event = events[0]
    assert event.actor_username == "pilot-expert"
    assert event.target_id == "rec-1"
    assert event.after == {"type": "accept", "reason": "below market"}
    assert event.correlation_id == "corr-audit-0001"


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_event SET reason = 'tampered'", "DELETE FROM audit_event"],
)
async def test_app_role_cannot_update_or_delete(db: Database, statement: str) -> None:
    async with db.tenant_session(TENANT_A) as session:
        await record(session, tenant_id=TENANT_A, actor=ACTOR, action="x.y", target_type="test")
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text(statement))


async def test_audit_events_are_tenant_isolated(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        await record(session, tenant_id=TENANT_A, actor=ACTOR, action="x.y", target_type="test")
    async with db.tenant_session(TENANT_B) as session:
        assert await list_events(session) == []


async def test_cannot_write_audit_event_for_another_tenant(db: Database) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.tenant_session(TENANT_A) as session:
            await record(session, tenant_id=TENANT_B, actor=ACTOR, action="x.y", target_type="test")
