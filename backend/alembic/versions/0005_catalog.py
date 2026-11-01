"""Catalog: product, variant, versioned cost_record and catalog_import.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from pricing_assistant.core.migration_helpers import app_role, enable_tenant_rls, grant

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        )
    ]


def upgrade() -> None:
    op.create_table(
        "product",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "category", "brand", "name", name="uq_product_identity"),
    )
    enable_tenant_rls("product")
    grant("product", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "variant",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("product.id"), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("mpn", sa.Text()),
        sa.Column("gtin", sa.Text()),
        sa.Column("attributes", JSONB(), nullable=False, server_default="{}"),
        sa.Column("importance_tier", sa.Text(), nullable=False, server_default="B"),
        sa.Column("current_price_rial", sa.BigInteger()),
        sa.Column("stock_quantity", sa.Integer()),
        sa.Column("cost_status", sa.Text(), nullable=False, server_default="cost_missing"),
        *_timestamps(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_variant_sku"),
        sa.CheckConstraint("importance_tier IN ('A', 'B', 'C')", name="importance_tier"),
        sa.CheckConstraint("cost_status IN ('ok', 'cost_missing')", name="cost_status"),
        sa.CheckConstraint(
            "current_price_rial IS NULL OR current_price_rial > 0", name="current_price"
        ),
        sa.CheckConstraint("stock_quantity IS NULL OR stock_quantity >= 0", name="stock"),
    )
    op.create_index("ix_variant_product_id", "variant", ["product_id"])
    op.create_index("ix_variant_mpn", "variant", ["tenant_id", "mpn"])
    op.create_index("ix_variant_gtin", "variant", ["tenant_id", "gtin"])
    enable_tenant_rls("variant")
    grant("variant", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "catalog_import",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("default_currency", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_held", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", JSONB(), nullable=False, server_default="[]"),
        sa.Column("uploaded_by", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('succeeded', 'partially_succeeded', 'failed', 'rejected')", name="status"
        ),
    )
    op.create_index(
        "ix_catalog_import_tenant_created", "catalog_import", ["tenant_id", "created_at"]
    )
    enable_tenant_rls("catalog_import")
    grant("catalog_import", ["SELECT", "INSERT"])
    # The job record's outcome is filled in while the import runs; file metadata is immutable.
    op.execute(
        "GRANT UPDATE (status, rows_total, rows_created, rows_updated, rows_unchanged, "
        f"rows_rejected, rows_held, errors) ON catalog_import TO {app_role()}"
    )

    op.create_table(
        "cost_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column("purchase_cost_rial", sa.BigInteger(), nullable=False),
        sa.Column("previous_cost_rial", sa.BigInteger()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("import_id", sa.Uuid(), sa.ForeignKey("catalog_import.id")),
        sa.Column("uploaded_by", sa.Text(), nullable=False),
        *_timestamps(),
        sa.Column("reviewed_by", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_reason", sa.Text()),
        sa.CheckConstraint("purchase_cost_rial > 0", name="positive_cost"),
        sa.CheckConstraint("state IN ('applied', 'held', 'confirmed', 'rejected')", name="state"),
    )
    op.create_index("ix_cost_record_variant", "cost_record", ["variant_id", "created_at"])
    enable_tenant_rls("cost_record")
    grant("cost_record", ["SELECT", "INSERT"])
    # Cost values are immutable; only the review of a held record may be written.
    op.execute(
        "GRANT UPDATE (state, reviewed_by, reviewed_at, review_reason) "
        f"ON cost_record TO {app_role()}"
    )


def downgrade() -> None:
    op.drop_table("cost_record")
    op.drop_table("catalog_import")
    op.drop_table("variant")
    op.drop_table("product")
