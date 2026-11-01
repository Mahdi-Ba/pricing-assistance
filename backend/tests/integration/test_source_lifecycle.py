import uuid
from datetime import date

import pytest
from sqlalchemy import select

from pricing_assistant.audit.api import list_events
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import Conflict, ValidationFailed
from pricing_assistant.core.events import OutboxEventRow
from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.models import RetrievalMethod, SourceStatus
from pricing_assistant.sources.registry import (
    SourceSettings,
    change_status,
    create_source,
    current_clearance,
    feeds_recommendations,
    get_source,
    grant_clearance,
    may_fetch,
    revoke_clearance,
    update_settings,
)
from tests.support.seed import ADMIN

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

SETTINGS = SourceSettings(
    quota_per_minute=30, interval_a_seconds=900, interval_b_seconds=3600, interval_c_seconds=21600
)


async def _new_source(db: Database) -> uuid.UUID:
    async with db.tenant_session(TENANT_A) as session:
        source = await create_source(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            name="Meghdad IT",
            base_domain="MeghdadIT.com",
            connector_key="generic_html",
            method=RetrievalMethod.HTML,
            currency_unit=CurrencyUnit.TOMAN,
            settings=SETTINGS,
        )
    return source.id


async def _grant(db: Database, source_id: uuid.UUID, permitted: int = 60) -> None:
    async with db.tenant_session(TENANT_A) as session:
        await grant_clearance(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=source_id,
            approver_name="Store owner",
            approved_on=date(2026, 10, 21),
            scope="public product pages, own offers only",
            reference="LEGAL-2026-07",
            permitted_requests_per_minute=permitted,
        )


async def _status(
    db: Database, source_id: uuid.UUID, target: SourceStatus, reason: str = "r"
) -> None:
    async with db.tenant_session(TENANT_A) as session:
        await change_status(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=source_id,
            target=target,
            reason=reason,
        )


async def test_evaluation_requires_clearance(db: Database) -> None:
    source_id = await _new_source(db)
    with pytest.raises(Conflict) as exc:
        await _status(db, source_id, SourceStatus.UNDER_EVALUATION)
    assert exc.value.problem_code == "clearance_missing"

    await _grant(db, source_id)
    await _status(db, source_id, SourceStatus.UNDER_EVALUATION, "phase A qualification")
    async with db.tenant_session(TENANT_A) as session:
        source = await get_source(session, source_id)
        assert await may_fetch(session, source)
    assert not feeds_recommendations(source.status)


async def test_quota_above_permitted_rate_is_rejected(db: Database) -> None:
    source_id = await _new_source(db)
    await _grant(db, source_id, permitted=30)
    with pytest.raises(ValidationFailed) as exc:
        async with db.tenant_session(TENANT_A) as session:
            await update_settings(
                session,
                tenant_id=TENANT_A,
                actor=ADMIN,
                source_id=source_id,
                settings=SourceSettings(120, 900, 3600, 21600),
            )
    assert exc.value.extra == {"permitted_requests_per_minute": 30}


async def test_clearance_below_current_quota_is_rejected(db: Database) -> None:
    source_id = await _new_source(db)
    with pytest.raises(ValidationFailed, match="Lower the source quota"):
        await _grant(db, source_id, permitted=10)


async def test_revoking_clearance_suspends_source_and_stops_fetching(db: Database) -> None:
    source_id = await _new_source(db)
    await _grant(db, source_id)
    await _status(db, source_id, SourceStatus.UNDER_EVALUATION)
    await _status(db, source_id, SourceStatus.APPROVED, "qualification passed")

    async with db.tenant_session(TENANT_A) as session:
        await revoke_clearance(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=source_id,
            reason="owner withdrew",
        )
    async with db.tenant_session(TENANT_A) as session:
        source = await get_source(session, source_id)
        assert source.status == "suspended"
        assert await current_clearance(session, source.id) is None
        assert not await may_fetch(session, source)
        actions = [e.action for e in await list_events(session)]
        events = [
            (e.type, e.payload["status"])
            for e in (await session.scalars(select(OutboxEventRow))).all()
        ]
    assert "source.clearance.revoked" in actions
    assert ("source.status.changed", "suspended") in events
    with pytest.raises(Conflict, match="clearance"):
        await _status(db, source_id, SourceStatus.APPROVED)


async def test_invalid_transitions_and_missing_reason(db: Database) -> None:
    source_id = await _new_source(db)
    with pytest.raises(Conflict, match="Cannot change"):
        await _status(db, source_id, SourceStatus.APPROVED)
    with pytest.raises(ValidationFailed):
        await _status(db, source_id, SourceStatus.REJECTED, reason=" ")
