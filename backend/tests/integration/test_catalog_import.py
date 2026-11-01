import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, list_events
from pricing_assistant.catalog.costs import (
    add_component,
    cost_history,
    deactivate_component,
    effective_cost,
    review_held_cost,
)
from pricing_assistant.catalog.importing import run_import
from pricing_assistant.catalog.models import CatalogImportRow, CostRecordRow, VariantRow
from pricing_assistant.catalog.upload import FileFormat, Upload
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import Conflict
from pricing_assistant.core.events import OutboxEventRow
from pricing_assistant.core.money import CurrencyUnit
from tests.support.catalog_files import csv_bytes, row, xlsx_bytes

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN = AuditActor(subject="admin-1", username="pilot-admin")


async def _import(
    db: Database,
    data: bytes,
    *,
    fmt: FileFormat = FileFormat.CSV,
    currency: CurrencyUnit | None = None,
) -> CatalogImportRow:
    async with db.tenant_session(TENANT_A) as session:
        return await run_import(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            upload=Upload(file_name=f"catalog.{fmt.value}", file_format=fmt, data=data),
            default_currency=currency,
            max_rows=1000,
        )


async def _count(session: AsyncSession, model: type[object]) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_valid_file_with_250_rows_is_imported(db: Database) -> None:
    rows = [row(f"SKU-{i:03d}", product_name=f"Product {i % 20}") for i in range(250)]
    result = await _import(db, xlsx_bytes(rows), fmt=FileFormat.XLSX)

    assert (result.status, result.rows_created, result.rows_updated, result.rows_unchanged) == (
        "succeeded",
        250,
        0,
        0,
    )
    async with db.tenant_session(TENANT_A) as session:
        assert await _count(session, VariantRow) == 250
        assert await _count(session, CostRecordRow) == 250
        events = {e.type for e in (await session.scalars(select(OutboxEventRow))).all()}
        audit = await list_events(session, action="catalog.import.completed")
    assert events == {"catalog.cost.changed", "catalog.variants.changed"}
    assert audit[0].after is not None
    assert audit[0].after["created"] == 250


async def test_identical_file_reimported_reports_all_unchanged(db: Database) -> None:
    data = csv_bytes([row("SSD-1"), row("SSD-2", model="990 PRO 2TB")])
    await _import(db, data)
    async with db.tenant_session(TENANT_A) as session:
        before = (await _count(session, VariantRow), await _count(session, CostRecordRow))
        events_before = await _count(session, OutboxEventRow)

    second = await _import(db, data)

    assert (second.rows_created, second.rows_updated, second.rows_unchanged) == (0, 0, 2)
    async with db.tenant_session(TENANT_A) as session:
        assert (await _count(session, VariantRow), await _count(session, CostRecordRow)) == before
        assert await _count(session, OutboxEventRow) == events_before


async def test_mixed_valid_and_invalid_rows(db: Database) -> None:
    rows = [row(f"SKU-{i}") for i in range(1, 11)]
    rows[3]["purchase_cost"] = "unknown"
    rows[6]["sku"] = ""

    result = await _import(db, csv_bytes(rows))

    assert result.status == "partially_succeeded"
    assert (result.rows_total, result.rows_created, result.rows_rejected) == (10, 8, 2)
    assert [(e["row"], e["column"]) for e in result.errors] == [(4, "purchase_cost"), (7, "sku")]
    assert all(e["message_fa"] for e in result.errors)


async def test_file_missing_required_column_is_rejected_before_processing(db: Database) -> None:
    columns = ("sku", "product_name", "category", "brand", "model", "current_price")
    result = await _import(db, csv_bytes([row("SSD-1")], columns=columns))

    assert result.status == "rejected"
    assert result.errors == [
        {
            "row": None,
            "column": "purchase_cost",
            "message_fa": "ستون الزامی «purchase_cost» در فایل وجود ندارد.",
        }
    ]
    async with db.tenant_session(TENANT_A) as session:
        assert await _count(session, VariantRow) == 0
        stored = await session.get(CatalogImportRow, result.id)
    assert stored is not None
    assert stored.status == "rejected"


async def test_missing_cost_marks_variant_cost_missing(db: Database) -> None:
    await _import(db, csv_bytes([row("SSD-1", purchase_cost="")]))
    async with db.tenant_session(TENANT_A) as session:
        variant = await session.scalar(select(VariantRow).where(VariantRow.sku == "SSD-1"))
        assert variant is not None
        assert variant.cost_status == "cost_missing"
        assert await effective_cost(session, variant.id) is None


async def test_toman_entered_as_rial_is_held_for_admin(db: Database) -> None:
    await _import(db, csv_bytes([row("SSD-1", purchase_cost="84,000,000", currency="RIAL")]))
    result = await _import(
        db, csv_bytes([row("SSD-1", purchase_cost="84,000,000", currency="TOMAN")])
    )

    assert result.rows_held == 1
    assert result.errors[0]["column"] == "purchase_cost"
    async with db.tenant_session(TENANT_A) as session:
        variant = await session.scalar(select(VariantRow).where(VariantRow.sku == "SSD-1"))
        assert variant is not None
        cost = await effective_cost(session, variant.id)
        history = await cost_history(session, variant.id)
    assert cost is not None
    assert cost.purchase_cost_rial == 84_000_000  # previous cost stays in force
    assert [
        (h.purchase_cost_rial, h.previous_cost_rial, h.state, h.uploaded_by) for h in history
    ] == [
        (840_000_000, 84_000_000, "held", "pilot-admin"),
        (84_000_000, None, "applied", "pilot-admin"),
    ]
    assert history[0].import_id == result.id


async def test_admin_confirms_or_rejects_held_cost(db: Database) -> None:
    await _import(db, csv_bytes([row("SSD-1", purchase_cost="1,000,000", currency="RIAL")]))
    await _import(db, csv_bytes([row("SSD-1", purchase_cost="9,000,000", currency="RIAL")]))
    async with db.tenant_session(TENANT_A) as session:
        variant = await session.scalar(select(VariantRow).where(VariantRow.sku == "SSD-1"))
        assert variant is not None
        held = (await cost_history(session, variant.id))[0]
        await review_held_cost(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            cost_record_id=held.id,
            confirm=True,
            reason="real price rise",
        )
    async with db.tenant_session(TENANT_A) as session:
        cost = await effective_cost(session, variant.id)
        assert cost is not None
        assert cost.purchase_cost_rial == 9_000_000
        with pytest.raises(Conflict):
            await review_held_cost(
                session,
                tenant_id=TENANT_A,
                actor=ADMIN,
                cost_record_id=held.id,
                confirm=False,
                reason="x",
            )
        audit = await list_events(session, action="catalog.cost.confirmed")
    assert audit[0].reason == "real price rise"


async def test_fixed_components_add_to_effective_cost(db: Database) -> None:
    await _import(
        db,
        csv_bytes(
            [
                row("SSD-1", purchase_cost="80,000,000", currency="RIAL"),
                row("GPU-1", category="gpu", purchase_cost="80,000,000", currency="RIAL"),
            ]
        ),
    )
    async with db.tenant_session(TENANT_A) as session:
        await add_component(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            name="حمل",
            amount_rial=1_500_000,
            category=None,
        )
        customs = await add_component(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            name="گمرک",
            amount_rial=500_000,
            category="ssd",
        )
    async with db.tenant_session(TENANT_A) as session:
        ssd = await session.scalar(select(VariantRow).where(VariantRow.sku == "SSD-1"))
        gpu = await session.scalar(select(VariantRow).where(VariantRow.sku == "GPU-1"))
        assert ssd is not None
        assert gpu is not None
        ssd_cost = await effective_cost(session, ssd.id)
        gpu_cost = await effective_cost(session, gpu.id)
        assert ssd_cost is not None
        assert gpu_cost is not None
        assert ssd_cost.total_rial == 82_000_000
        assert gpu_cost.total_rial == 81_500_000
        await deactivate_component(
            session, tenant_id=TENANT_A, actor=ADMIN, component_id=customs.id, reason="duty removed"
        )
        after = await effective_cost(session, ssd.id)
    assert after is not None
    assert after.total_rial == 81_500_000
