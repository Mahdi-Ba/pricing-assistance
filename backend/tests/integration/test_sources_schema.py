import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.models import ExtractionRuleVersionRow, SourceClearanceRow
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration


async def test_clearances_are_append_only(db: Database) -> None:
    await seed_source(db, TENANT_A)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text("UPDATE source_clearance SET reference = 'x'"))


async def test_granted_clearance_must_be_complete(db: Database) -> None:
    source_id = await seed_source(db, TENANT_A, cleared=False)
    with pytest.raises(IntegrityError, match="grant_complete"):
        async with db.tenant_session(TENANT_A) as session:
            session.add(
                SourceClearanceRow(
                    id=new_id(),
                    tenant_id=TENANT_A,
                    source_id=source_id,
                    kind="granted",
                    approver_name="Owner",
                    recorded_by="t",
                )
            )


async def test_only_one_active_extraction_rule_per_source(db: Database) -> None:
    source_id = await seed_source(db, TENANT_A)
    with pytest.raises(IntegrityError, match="uq_extraction_rule_one_active"):
        async with db.tenant_session(TENANT_A) as session:
            for version in (1, 2):
                session.add(
                    ExtractionRuleVersionRow(
                        id=new_id(),
                        tenant_id=TENANT_A,
                        source_id=source_id,
                        version=version,
                        config={},
                        state="active",
                        origin="admin",
                        created_by="t",
                    )
                )
                await session.flush()


async def test_offer_cannot_be_own_store_and_own_channel(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A)
    with pytest.raises(IntegrityError, match="own_flags"):
        await seed_offer(
            db, TENANT_A, source_id=source, variant_id=variant, own_store=True, own_channel=True
        )


async def test_sources_are_tenant_isolated(db: Database) -> None:
    await seed_source(db, TENANT_A)
    async with db.tenant_session(TENANT_B) as session:
        count = (await session.execute(text("SELECT count(*) FROM source"))).scalar_one()
    assert count == 0
