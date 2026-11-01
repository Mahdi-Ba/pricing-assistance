import uuid
from datetime import UTC, datetime, timedelta

import pytest

from pricing_assistant.collection.health import source_health
from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.config import put_config
from tests.support.api import api_client, auth
from tests.support.seed import ADMIN, seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


async def _attempt(
    db: Database, offer: uuid.UUID, source: uuid.UUID, ago: timedelta, error: str | None
) -> uuid.UUID:
    async with db.tenant_session(TENANT_A) as session:
        row = FetchAttemptRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=source,
            window_start=NOW - ago,
            attempt=1,
            trigger="scheduled",
            outcome="failure" if error else "success",
            error_class=error,
            final=True,
            correlation_id="corr-h",
            finished_at=NOW - ago,
        )
        session.add(row)
    return row.id


async def test_24h_health_view_matches_seeded_attempts(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A, name="Lion")
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    idle_offer = await seed_offer(
        db, TENANT_A, source_id=source, variant_id=variant, url="https://www.lioncomputer.com/other"
    )
    outcomes = [None] * 7 + ["blocked", "parse_failure", "parse_failure"]
    attempt_ids = [
        await _attempt(db, offer, source, timedelta(hours=i + 1), error)
        for i, error in enumerate(outcomes)
    ]
    await _attempt(db, offer, source, timedelta(hours=30), "network")  # outside the window
    async with db.tenant_session(TENANT_A) as session:
        session.add(
            ObservationRow(
                id=new_id(),
                tenant_id=TENANT_A,
                tracked_offer_id=offer,
                source_id=source,
                variant_id=variant,
                fetch_attempt_id=attempt_ids[0],
                observed_at=NOW - timedelta(minutes=90),
                url="https://www.lioncomputer.com/product/990-pro-1tb",
                method="html",
                price_rial=86_000_000,
                stock_state="in_stock",
                conditions={},
                identifiers={},
                validity="valid",
                is_own_store=False,
                is_own_channel=False,
                evidence_ids=[],
            )
        )
        await put_config(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=source,
            config={"estimated_cost_per_request_rial": 2_000},
        )
        [health] = await source_health(session, hours=24, now=NOW)

    assert (health.requests, health.successes, health.success_rate) == (10, 7, 0.7)
    assert health.errors == {"blocked": 1, "parse_failure": 2}
    assert health.blocked == 1
    assert health.data_age_median_seconds == 5400
    assert health.data_age_max_seconds == 5400
    assert health.offers_without_observation == 1
    assert health.estimated_cost_rial == 20_000
    assert idle_offer


async def test_health_endpoint_is_admin_only(db: Database) -> None:
    await seed_source(db, TENANT_A)
    async with api_client(db) as client:
        admin = await client.get("/sources-health?hours=24", headers=auth(TENANT_A, "admin"))
        expert = await client.get("/sources-health", headers=auth(TENANT_A, "expert"))
    assert admin.status_code == 200
    assert admin.json()[0]["requests"] == 0
    assert expert.status_code == 403
