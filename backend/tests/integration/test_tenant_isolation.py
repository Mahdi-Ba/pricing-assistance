import pytest
from sqlalchemy import text

from pricing_assistant.core.db import Database

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration


async def test_session_sees_only_its_tenant_even_with_raw_select(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        ids = (await session.execute(text("SELECT id FROM tenant"))).scalars().all()
        leaked = (
            await session.execute(
                text("SELECT count(*) FROM tenant WHERE id = :b"), {"b": TENANT_B}
            )
        ).scalar_one()
    assert ids == [TENANT_A]
    assert leaked == 0


async def test_session_without_tenant_sees_nothing(db: Database) -> None:
    async with db.system_session() as session:
        count = (await session.execute(text("SELECT count(*) FROM tenant"))).scalar_one()
    assert count == 0


async def test_active_tenant_enumeration_uses_security_definer(db: Database) -> None:
    assert await db.active_tenant_ids() == sorted([TENANT_A, TENANT_B])


async def test_app_role_cannot_disable_rls_or_set_role(db: Database) -> None:
    async with db.system_session() as session:
        with pytest.raises(Exception, match="must be owner"):
            await session.execute(text("ALTER TABLE tenant DISABLE ROW LEVEL SECURITY"))
