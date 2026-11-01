"""Catalog import: validates a file and upserts variants and costs (tasks 3.3–3.5, 3.11).

Imports are idempotent: variants are upserted by SKU and compared field by field, and a new
cost version is written only when the value differs from the one in force. Re-uploading the
same file therefore reports every row as unchanged and writes no business records.
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.catalog.events import CostChanged, VariantsChanged
from pricing_assistant.catalog.models import (
    IN_FORCE_STATES,
    CatalogImportRow,
    CostRecordRow,
    CostRecordState,
    CostStatus,
    ImportStatus,
    ProductRow,
    VariantRow,
)
from pricing_assistant.catalog.template import (
    CatalogRow,
    ParsedTable,
    RowError,
    TemplateMismatchError,
    check_headers,
    parse_table,
    validate_row,
)
from pricing_assistant.catalog.upload import Upload
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.money import CurrencyUnit

# A new cost outside [previous / 5, previous * 5] is most likely a Rial/Toman mix-up.
SUSPECT_RATIO = 5


@dataclass
class ImportOutcome:
    import_id: uuid.UUID
    status: ImportStatus
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    held: int = 0
    errors: list[RowError] = field(default_factory=list)
    cost_changed: list[uuid.UUID] = field(default_factory=list)
    variants_changed: list[uuid.UUID] = field(default_factory=list)


def is_suspect_cost(new_cost: int, previous_cost: int | None) -> bool:
    if previous_cost is None or previous_cost <= 0:
        return False
    return new_cost > previous_cost * SUSPECT_RATIO or new_cost * SUSPECT_RATIO < previous_cost


async def current_cost(session: AsyncSession, variant_id: uuid.UUID) -> CostRecordRow | None:
    """The cost version in force: the newest applied or confirmed record."""
    result: CostRecordRow | None = await session.scalar(
        select(CostRecordRow)
        .where(CostRecordRow.variant_id == variant_id, CostRecordRow.state.in_(IN_FORCE_STATES))
        .order_by(CostRecordRow.created_at.desc(), CostRecordRow.id.desc())
        .limit(1)
    )
    return result


async def _product_for(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    row: CatalogRow,
    cache: dict[tuple[str, str, str], ProductRow],
) -> ProductRow:
    key = (row.category, row.brand, row.product_name)
    if key in cache:
        return cache[key]
    product = await session.scalar(
        select(ProductRow).where(
            ProductRow.category == row.category,
            ProductRow.brand == row.brand,
            ProductRow.name == row.product_name,
        )
    )
    if product is None:
        product = ProductRow(
            id=new_id(),
            tenant_id=tenant_id,
            category=row.category,
            brand=row.brand,
            name=row.product_name,
        )
        session.add(product)
        await session.flush()
    cache[key] = product
    return product


def _variant_values(row: CatalogRow, product_id: uuid.UUID) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "model": row.model,
        "mpn": row.mpn,
        "gtin": row.gtin,
        "attributes": row.attributes,
        "importance_tier": row.importance_tier.value,
        "current_price_rial": row.current_price_rial,
        "stock_quantity": row.stock_quantity,
    }


async def _apply_cost(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    variant: VariantRow,
    new_cost: int,
    import_id: uuid.UUID,
    actor: AuditActor,
    outcome: ImportOutcome,
    row_number: int,
) -> bool:
    """Write a cost version if it differs; return True if anything was written."""
    in_force = await current_cost(session, variant.id)
    previous = in_force.purchase_cost_rial if in_force else None
    if previous == new_cost:
        return False
    suspect = is_suspect_cost(new_cost, previous)
    session.add(
        CostRecordRow(
            id=new_id(),
            tenant_id=tenant_id,
            variant_id=variant.id,
            purchase_cost_rial=new_cost,
            previous_cost_rial=previous,
            state=(CostRecordState.HELD if suspect else CostRecordState.APPLIED).value,
            import_id=import_id,
            uploaded_by=actor.username,
        )
    )
    if suspect:
        outcome.held += 1
        outcome.errors.append(
            RowError(
                row_number,
                "purchase_cost",
                "هزینه جدید بیش از ۵ برابر با هزینه قبلی تفاوت دارد و تا تأیید مدیر اعمال نمی‌شود "
                "(احتمال اشتباه ریال/تومان).",
            )
        )
    else:
        variant.cost_status = CostStatus.OK.value
        outcome.cost_changed.append(variant.id)
    return True


async def _upsert(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    rows: list[CatalogRow],
    import_id: uuid.UUID,
    actor: AuditActor,
    outcome: ImportOutcome,
) -> None:
    products: dict[tuple[str, str, str], ProductRow] = {}
    existing = {
        v.sku: v
        for v in (
            await session.scalars(
                select(VariantRow).where(VariantRow.sku.in_([r.sku for r in rows]))
            )
        ).all()
    }
    for row in rows:
        product = await _product_for(session, tenant_id, row, products)
        values = _variant_values(row, product.id)
        variant = existing.get(row.sku)
        created = variant is None
        changed = False
        if variant is None:
            variant = VariantRow(id=new_id(), tenant_id=tenant_id, sku=row.sku, **values)
            variant.cost_status = CostStatus.COST_MISSING.value
            session.add(variant)
            await session.flush()
            existing[row.sku] = variant
        else:
            for name, value in values.items():
                if getattr(variant, name) != value:
                    setattr(variant, name, value)
                    changed = True
            if changed:
                variant.updated_at = datetime.now(UTC)
        cost_written = False
        if row.purchase_cost_rial is not None:
            cost_written = await _apply_cost(
                session,
                tenant_id=tenant_id,
                variant=variant,
                new_cost=row.purchase_cost_rial,
                import_id=import_id,
                actor=actor,
                outcome=outcome,
                row_number=row.row,
            )
        if created:
            outcome.created += 1
            outcome.variants_changed.append(variant.id)
        elif changed or cost_written:
            outcome.updated += 1
            if changed:
                outcome.variants_changed.append(variant.id)
        else:
            outcome.unchanged += 1


def _status(outcome: ImportOutcome, total: int) -> ImportStatus:
    if total and outcome.rejected == total:
        return ImportStatus.FAILED
    if outcome.rejected:
        return ImportStatus.PARTIALLY_SUCCEEDED
    return ImportStatus.SUCCEEDED


def _validate_rows(
    table: ParsedTable, default_currency: CurrencyUnit | None, outcome: ImportOutcome
) -> list[CatalogRow]:
    valid: list[CatalogRow] = []
    seen: set[str] = set()
    for number, values in table.rows:
        result = validate_row(number, values, default_currency)
        if isinstance(result, list):
            outcome.rejected += 1
            outcome.errors.extend(result)
        elif result.sku in seen:
            outcome.rejected += 1
            outcome.errors.append(RowError(number, "sku", "کد کالا (SKU) در این فایل تکراری است."))
        else:
            seen.add(result.sku)
            valid.append(result)
    return valid


def _parse(upload: Upload, max_rows: int, outcome: ImportOutcome) -> ParsedTable | None:
    """Parse and check the header; on failure mark the whole import rejected."""
    try:
        table = parse_table(upload.data, upload.file_format, max_rows=max_rows)
        check_headers(table.headers)
    except TemplateMismatchError as exc:
        outcome.status = ImportStatus.REJECTED
        outcome.errors = [
            RowError(None, column, f"ستون الزامی «{column}» در فایل وجود ندارد.")
            for column in exc.missing
        ]
        return None
    except ValueError as exc:
        outcome.status = ImportStatus.REJECTED
        outcome.errors = [
            RowError(None, None, f"فایل قابل خواندن نیست یا بیش از حد بزرگ است: {exc}")
        ]
        return None
    return table


def _summary(outcome: ImportOutcome) -> dict[str, Any]:
    return {
        "status": outcome.status.value,
        "created": outcome.created,
        "updated": outcome.updated,
        "unchanged": outcome.unchanged,
        "rejected": outcome.rejected,
        "held": outcome.held,
    }


async def run_import(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    upload: Upload,
    default_currency: CurrencyUnit | None,
    max_rows: int,
) -> CatalogImportRow:
    """Validate and apply one catalog file inside the caller's transaction."""
    import_row = CatalogImportRow(
        id=new_id(),
        tenant_id=tenant_id,
        file_name=upload.file_name[:255],
        media_type=upload.media_type,
        size_bytes=len(upload.data),
        content_hash=hashlib.sha256(upload.data).hexdigest(),
        default_currency=default_currency.value if default_currency else None,
        status=ImportStatus.REJECTED.value,
        uploaded_by=actor.username,
    )
    session.add(import_row)
    await session.flush()
    outcome = ImportOutcome(import_id=import_row.id, status=ImportStatus.SUCCEEDED)
    table = _parse(upload, max_rows, outcome)
    if table is not None:
        valid = _validate_rows(table, default_currency, outcome)
        await _upsert(
            session,
            tenant_id=tenant_id,
            rows=valid,
            import_id=import_row.id,
            actor=actor,
            outcome=outcome,
        )
        outcome.status = _status(outcome, len(table.rows))
        import_row.rows_total = len(table.rows)

    import_row.status = outcome.status.value
    import_row.rows_created = outcome.created
    import_row.rows_updated = outcome.updated
    import_row.rows_unchanged = outcome.unchanged
    import_row.rows_rejected = outcome.rejected
    import_row.rows_held = outcome.held
    import_row.errors = [e.as_dict() for e in outcome.errors]
    await session.flush()

    if outcome.cost_changed:
        await publish(
            session,
            tenant_id=tenant_id,
            event=CostChanged(variant_ids=outcome.cost_changed, reason="catalog_import"),
        )
    if outcome.variants_changed:
        await publish(
            session,
            tenant_id=tenant_id,
            event=VariantsChanged(variant_ids=outcome.variants_changed),
        )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="catalog.import.completed",
        target_type="catalog_import",
        target_id=import_row.id,
        after={
            "file_name": upload.file_name,
            "content_hash": import_row.content_hash,
            **_summary(outcome),
        },
    )
    return import_row
