"""Catalog persistence: products, variants, versioned purchase costs and import jobs."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class ImportanceTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class CostStatus(StrEnum):
    OK = "ok"
    COST_MISSING = "cost_missing"


class CostRecordState(StrEnum):
    APPLIED = "applied"  # in force from creation
    HELD = "held"  # suspect_unit: waits for admin confirmation
    CONFIRMED = "confirmed"  # held, then confirmed by an admin; in force
    REJECTED = "rejected"  # held, then rejected; never in force


IN_FORCE_STATES = (CostRecordState.APPLIED.value, CostRecordState.CONFIRMED.value)


class ImportStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class ProductRow(Base):
    __tablename__ = "product"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    category: Mapped[str] = mapped_column(Text)
    brand: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VariantRow(Base):
    __tablename__ = "variant"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("product.id"))
    sku: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    mpn: Mapped[str | None] = mapped_column(Text)
    gtin: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    importance_tier: Mapped[str] = mapped_column(Text, server_default=ImportanceTier.B.value)
    current_price_rial: Mapped[int | None] = mapped_column(BigInteger)
    stock_quantity: Mapped[int | None] = mapped_column(Integer)
    cost_status: Mapped[str] = mapped_column(Text, server_default=CostStatus.COST_MISSING.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CostRecordRow(Base):
    """One version of a variant's purchase cost. Values are immutable; only the review state
    of a held record may change (held → confirmed | rejected)."""

    __tablename__ = "cost_record"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    purchase_cost_rial: Mapped[int] = mapped_column(BigInteger)
    previous_cost_rial: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(Text)
    import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("catalog_import.id"))
    uploaded_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)


class CatalogImportRow(Base):
    __tablename__ = "catalog_import"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    file_name: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(Text)
    default_currency: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    rows_total: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_created: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_updated: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_unchanged: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_held: Mapped[int] = mapped_column(Integer, server_default="0")
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    uploaded_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
