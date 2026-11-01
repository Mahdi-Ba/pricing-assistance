"""Collection: append-only observation and fetch_attempt, fetch_claim, recheck_request.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from pricing_assistant.core.migration_helpers import (
    app_role,
    enable_tenant_rls,
    grant,
    grant_append_only,
    maintenance_role,
)

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fetch_attempt",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error_class", sa.Text()),
        sa.Column("detail", sa.Text()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("offers_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("final", sa.Boolean(), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column(
            "finished_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("outcome IN ('success', 'failure')", name="outcome"),
        sa.CheckConstraint("trigger IN ('scheduled', 'recheck', 'qualification')", name="trigger"),
        sa.CheckConstraint("attempt >= 1", name="attempt"),
    )
    op.create_index(
        "ix_fetch_attempt_source_time", "fetch_attempt", ["tenant_id", "source_id", "finished_at"]
    )
    op.create_index(
        "ix_fetch_attempt_offer_time", "fetch_attempt", ["tracked_offer_id", "finished_at"]
    )
    enable_tenant_rls("fetch_attempt")
    grant_append_only("fetch_attempt")

    op.create_table(
        "observation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column("fetch_attempt_id", sa.Uuid(), sa.ForeignKey("fetch_attempt.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("seller", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("price_rial", sa.BigInteger()),
        sa.Column("stock_state", sa.Text(), nullable=False),
        sa.Column("conditions", JSONB(), nullable=False, server_default="{}"),
        sa.Column("identifiers", JSONB(), nullable=False, server_default="{}"),
        sa.Column("validity", sa.Text(), nullable=False),
        sa.Column("is_own_store", sa.Boolean(), nullable=False),
        sa.Column("is_own_channel", sa.Boolean(), nullable=False),
        sa.Column("extraction_rule_version_id", sa.Uuid()),
        sa.Column("evidence_ids", ARRAY(sa.Uuid()), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "stock_state IN ('in_stock', 'out_of_stock', 'unknown')", name="stock_state"
        ),
        sa.CheckConstraint("validity IN ('valid', 'suspect_unit')", name="validity"),
        sa.CheckConstraint("price_rial IS NULL OR price_rial > 0", name="price"),
        sa.CheckConstraint(
            "price_rial IS NOT NULL OR stock_state = 'out_of_stock'", name="price_or_oos"
        ),
    )
    op.create_index("ix_observation_offer_time", "observation", ["tracked_offer_id", "observed_at"])
    op.create_index("ix_observation_variant_time", "observation", ["variant_id", "observed_at"])
    op.create_index("ix_observation_tenant_time", "observation", ["tenant_id", "observed_at"])
    enable_tenant_rls("observation")
    grant_append_only("observation")

    op.create_table(
        "fetch_claim",
        sa.Column(
            "tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), primary_key=True
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column(
            "claimed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    enable_tenant_rls("fetch_claim")
    grant_append_only("fetch_claim")

    op.create_table(
        "recheck_request",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("fetch_attempt_id", sa.Uuid(), sa.ForeignKey("fetch_attempt.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'completed', 'failed')", name="status"),
    )
    enable_tenant_rls("recheck_request")
    grant("recheck_request", ["SELECT", "INSERT"])
    op.execute(
        f"GRANT UPDATE (status, fetch_attempt_id, completed_at) ON recheck_request TO {app_role()}"
    )

    # Retention purges (task 5.11) run as the maintenance role only.
    maintenance = maintenance_role()
    for table in ("observation", "fetch_attempt", "fetch_claim"):
        grant(table, ["SELECT", "DELETE"], maintenance)


def downgrade() -> None:
    op.drop_table("recheck_request")
    op.drop_table("fetch_claim")
    op.drop_table("observation")
    op.drop_table("fetch_attempt")
