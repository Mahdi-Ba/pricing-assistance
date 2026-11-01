"""Seed helpers for integration tests."""

import uuid
from datetime import UTC, date, datetime

from pricing_assistant.audit.api import AuditActor
from pricing_assistant.catalog.models import ProductRow, VariantRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.models import (
    SourceClearanceRow,
    SourceRow,
    SourceStatus,
    TrackedOfferRow,
    TrackedOfferStatus,
)

ADMIN = AuditActor(subject="admin-1", username="pilot-admin")


async def seed_variant(
    db: Database,
    tenant_id: uuid.UUID,
    *,
    sku: str = "SSD-1",
    category: str = "ssd",
    tier: str = "A",
    price_rial: int | None = 89_000_000,
    brand: str = "Samsung",
    model: str = "990 PRO",
    mpn: str | None = None,
    gtin: str | None = None,
    attributes: dict[str, object] | None = None,
) -> uuid.UUID:
    async with db.tenant_session(tenant_id) as session:
        product = ProductRow(
            id=new_id(), tenant_id=tenant_id, category=category, brand=brand, name=f"P-{sku}"
        )
        session.add(product)
        await session.flush()
        variant = VariantRow(
            id=new_id(),
            tenant_id=tenant_id,
            product_id=product.id,
            sku=sku,
            model=model,
            mpn=mpn,
            gtin=gtin,
            attributes=attributes
            if attributes is not None
            else {"capacity": "1TB", "warranty_provider": "آواژنگ", "warranty_months": 36},
            importance_tier=tier,
            current_price_rial=price_rial,
        )
        session.add(variant)
    return variant.id


async def seed_source(
    db: Database,
    tenant_id: uuid.UUID,
    *,
    name: str = "Lion Computer",
    status: SourceStatus = SourceStatus.APPROVED,
    method: str = "html",
    quota: int = 30,
    cleared: bool = True,
    connector_key: str = "generic_html",
    base_domain: str = "www.lioncomputer.com",
) -> uuid.UUID:
    async with db.tenant_session(tenant_id) as session:
        source = SourceRow(
            id=new_id(),
            tenant_id=tenant_id,
            name=name,
            base_domain=base_domain,
            connector_key=connector_key,
            method=method,
            currency_unit="TOMAN",
            quota_per_minute=quota,
            interval_a_seconds=900,
            interval_b_seconds=3600,
            interval_c_seconds=21600,
            status=status.value,
            created_by="seed",
        )
        session.add(source)
        await session.flush()
        if cleared:
            session.add(
                SourceClearanceRow(
                    id=new_id(),
                    tenant_id=tenant_id,
                    source_id=source.id,
                    kind="granted",
                    approver_name="Store owner",
                    approved_on=date(2026, 10, 20),
                    scope="public product pages",
                    reference="LEGAL-42",
                    permitted_requests_per_minute=max(60, quota),
                    recorded_by="seed",
                )
            )
    return source.id


async def seed_offer(
    db: Database,
    tenant_id: uuid.UUID,
    *,
    source_id: uuid.UUID,
    variant_id: uuid.UUID,
    url: str = "https://www.lioncomputer.com/product/990-pro-1tb",
    own_store: bool = False,
    own_channel: bool = False,
    due: datetime | None = None,
) -> uuid.UUID:
    async with db.tenant_session(tenant_id) as session:
        offer = TrackedOfferRow(
            id=new_id(),
            tenant_id=tenant_id,
            source_id=source_id,
            variant_id=variant_id,
            url=url,
            status=TrackedOfferStatus.ACTIVE.value,
            is_own_store=own_store,
            is_own_channel=own_channel,
            next_due_at=due or datetime.now(UTC),
            created_by="seed",
        )
        session.add(offer)
    return offer.id


async def seed_cost(
    db: Database, tenant_id: uuid.UUID, variant_id: uuid.UUID, cost_rial: int
) -> uuid.UUID:
    from pricing_assistant.catalog.models import CostRecordRow  # noqa: PLC0415

    async with db.tenant_session(tenant_id) as session:
        record = CostRecordRow(
            id=new_id(),
            tenant_id=tenant_id,
            variant_id=variant_id,
            purchase_cost_rial=cost_rial,
            state="applied",
            uploaded_by="seed",
        )
        session.add(record)
        variant = await session.get(VariantRow, variant_id)
        assert variant is not None
        variant.cost_status = "ok"
    return record.id
