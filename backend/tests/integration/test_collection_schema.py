from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration


async def _observation(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    now = datetime.now(UTC)
    async with db.tenant_session(TENANT_A) as session:
        attempt = FetchAttemptRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=source,
            window_start=now,
            attempt=1,
            trigger="scheduled",
            outcome="success",
            offers_count=1,
            final=True,
            correlation_id="corr-x",
        )
        session.add(attempt)
        await session.flush()
        session.add(
            ObservationRow(
                id=new_id(),
                tenant_id=TENANT_A,
                tracked_offer_id=offer,
                source_id=source,
                variant_id=variant,
                fetch_attempt_id=attempt.id,
                observed_at=now,
                url="https://x.test/p",
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


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE observation SET price_rial = 1",
        "DELETE FROM observation",
        "UPDATE fetch_attempt SET outcome = 'success'",
        "DELETE FROM fetch_attempt",
    ],
)
async def test_app_role_cannot_update_or_delete_observations(db: Database, statement: str) -> None:
    await _observation(db)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text(statement))
