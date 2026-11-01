import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from pricing_assistant.catalog.models import CostRecordRow, ProductRow, VariantRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration


async def _variant(db: Database, tenant: object, sku: str) -> VariantRow:
    async with db.tenant_session(tenant) as session:  # type: ignore[arg-type]
        product = ProductRow(
            id=new_id(), tenant_id=tenant, category="ssd", brand="Samsung", name="990 PRO"
        )
        variant = VariantRow(
            id=new_id(), tenant_id=tenant, product_id=product.id, sku=sku, model="990 PRO 1TB"
        )
        session.add(product)
        await session.flush()
        session.add(variant)
    return variant


async def test_sku_is_unique_per_tenant_but_reusable_across_tenants(db: Database) -> None:
    await _variant(db, TENANT_A, "SSD-1")
    await _variant(db, TENANT_B, "SSD-1")
    with pytest.raises(IntegrityError):
        async with db.tenant_session(TENANT_A) as session:
            product = ProductRow(
                id=new_id(), tenant_id=TENANT_A, category="ssd", brand="X", name="Y"
            )
            session.add(product)
            await session.flush()
            session.add(
                VariantRow(
                    id=new_id(), tenant_id=TENANT_A, product_id=product.id, sku="SSD-1", model="m"
                )
            )


async def test_cost_values_are_immutable_but_review_state_is_writable(db: Database) -> None:
    variant = await _variant(db, TENANT_A, "SSD-2")
    async with db.tenant_session(TENANT_A) as session:
        record = CostRecordRow(
            id=new_id(),
            tenant_id=TENANT_A,
            variant_id=variant.id,
            purchase_cost_rial=80_000_000,
            state="held",
            uploaded_by="pilot-admin",
        )
        session.add(record)
    async with db.tenant_session(TENANT_A) as session:
        await session.execute(
            text("UPDATE cost_record SET state = 'confirmed', reviewed_by = 'pilot-admin'")
        )
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text("UPDATE cost_record SET purchase_cost_rial = 1"))
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text("DELETE FROM cost_record"))


async def test_catalog_rows_are_tenant_isolated(db: Database) -> None:
    await _variant(db, TENANT_A, "SSD-3")
    async with db.tenant_session(TENANT_B) as session:
        assert (await session.scalars(select(VariantRow))).all() == []
        assert (await session.scalars(select(ProductRow))).all() == []
