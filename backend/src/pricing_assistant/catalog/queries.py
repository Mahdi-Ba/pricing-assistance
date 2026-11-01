"""Read helpers other modules use through `catalog.api`."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.models import ImportanceTier, ProductRow, VariantRow


@dataclass(frozen=True, slots=True)
class VariantInfo:
    id: uuid.UUID
    sku: str
    product_name: str
    category: str
    brand: str
    model: str
    mpn: str | None
    gtin: str | None
    attributes: dict[str, Any]
    importance_tier: ImportanceTier
    current_price_rial: int | None
    stock_quantity: int | None
    cost_status: str
    updated_at: datetime


async def variant_exists(session: AsyncSession, variant_id: uuid.UUID) -> bool:
    return (
        await session.scalar(select(VariantRow.id).where(VariantRow.id == variant_id)) is not None
    )


def _info(variant: VariantRow, product: ProductRow) -> VariantInfo:
    return VariantInfo(
        id=variant.id,
        sku=variant.sku,
        product_name=product.name,
        category=product.category,
        brand=product.brand,
        model=variant.model,
        mpn=variant.mpn,
        gtin=variant.gtin,
        attributes=dict(variant.attributes),
        importance_tier=ImportanceTier(variant.importance_tier),
        current_price_rial=variant.current_price_rial,
        stock_quantity=variant.stock_quantity,
        cost_status=variant.cost_status,
        updated_at=variant.updated_at,
    )


async def get_variant(session: AsyncSession, variant_id: uuid.UUID) -> VariantInfo | None:
    row = (
        await session.execute(
            select(VariantRow, ProductRow)
            .join(ProductRow, VariantRow.product_id == ProductRow.id)
            .where(VariantRow.id == variant_id)
        )
    ).first()
    return _info(row[0], row[1]) if row else None


async def list_variants(
    session: AsyncSession, variant_ids: list[uuid.UUID] | None = None
) -> list[VariantInfo]:
    query = select(VariantRow, ProductRow).join(ProductRow, VariantRow.product_id == ProductRow.id)
    if variant_ids is not None:
        query = query.where(VariantRow.id.in_(variant_ids))
    rows = await session.execute(query.order_by(VariantRow.sku))
    return [_info(v, p) for v, p in rows.all()]
