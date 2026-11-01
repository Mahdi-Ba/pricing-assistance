from datetime import UTC, datetime, timedelta

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from pricing_assistant.audit.api import list_events
from pricing_assistant.collection.evidence import EvidenceObjectRow, EvidenceStore
from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.models import ObservationRow
from pricing_assistant.collection.retention import PurgeLogRow, missing_observations, purge
from pricing_assistant.core import tenant_settings
from pricing_assistant.core.db import Database
from pricing_assistant.core.settings import get_settings
from tests.support.api import api_client, auth
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A
from .test_collection_pipeline import envelope

pytestmark = pytest.mark.integration


async def _observe(db: Database, redis: Redis) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, quota=600)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    runtime, _ = await collection_runtime(db, redis, RecordingConnector())
    await handle_fetch(runtime, envelope(offer))


async def test_evidence_expires_and_link_reports_it(
    db: Database, maintenance_db: Database, redis_client: Redis
) -> None:
    await _observe(db, redis_client)
    store = EvidenceStore(get_settings())
    async with db.tenant_session(TENANT_A) as session:
        evidence = (await session.scalars(select(EvidenceObjectRow))).all()
        observation_ids = list((await session.scalars(select(ObservationRow.id))).all())
    url = store.presign(evidence[0].object_key, evidence[0].content_type)

    results = await purge(maintenance_db, store, now=datetime.now(UTC) + timedelta(days=91))
    result = next(r for r in results if r.tenant_id == TENANT_A)

    assert result.evidence_expired == len(evidence)
    assert result.observations_deleted == 0  # history kept indefinitely by default
    async with httpx.AsyncClient() as client:
        assert (await client.get(url)).status_code == 404  # object gone from storage
    async with api_client(db) as client:
        link = await client.get(f"/evidence/{evidence[0].id}", headers=auth(TENANT_A, "expert"))
    assert link.status_code == 404
    assert link.json()["type"].endswith("evidence_expired")
    async with db.tenant_session(TENANT_A) as session:
        assert await missing_observations(session, observation_ids) == set()


async def test_configured_observation_retention_purges_with_audit(
    db: Database, maintenance_db: Database, redis_client: Redis
) -> None:
    await _observe(db, redis_client)
    async with db.tenant_session(TENANT_A) as session:
        await tenant_settings.update(
            session, TENANT_A, {"observation_retention_days": 365}, "admin"
        )
        observation_ids = list((await session.scalars(select(ObservationRow.id))).all())

    results = await purge(
        maintenance_db, EvidenceStore(get_settings()), now=datetime.now(UTC) + timedelta(days=400)
    )
    result = next(r for r in results if r.tenant_id == TENANT_A)

    assert result.observations_deleted == 1
    async with db.tenant_session(TENANT_A) as session:
        assert await session.scalar(select(func.count()).select_from(ObservationRow)) == 0
        logs = (await session.scalars(select(PurgeLogRow).order_by(PurgeLogRow.kind))).all()
        audit = await list_events(session, action="retention.observation.purged")
        assert await missing_observations(session, observation_ids) == set(observation_ids)
    assert [(log.kind, log.deleted_count) for log in logs] == [("evidence", 2), ("observation", 1)]
    assert audit[0].after is not None
    assert audit[0].after["deleted"] == 1
    assert audit[0].actor_username == "system"


async def test_only_the_maintenance_role_may_delete_observations(
    db: Database, maintenance_db: Database, redis_client: Redis
) -> None:
    await _observe(db, redis_client)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text("DELETE FROM observation"))
    async with maintenance_db.tenant_session(TENANT_A) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(text("UPDATE observation SET price_rial = 1"))
