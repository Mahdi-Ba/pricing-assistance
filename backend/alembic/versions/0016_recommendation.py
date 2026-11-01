"""Append-only recommendation and outlier_confirmation.

Revision ID: 0016
Revises: 0015
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

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuids(name: str) -> sa.Column[list[object]]:
    return sa.Column(name, ARRAY(sa.Uuid()), nullable=False, server_default="{}")


def upgrade() -> None:
    op.create_table(
        "recommendation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("flags", JSONB(), nullable=False, server_default="[]"),
        sa.Column("suggested_price_rial", sa.BigInteger()),
        sa.Column("our_price_rial", sa.BigInteger()),
        sa.Column("floor_rial", sa.BigInteger()),
        sa.Column("ceiling_rial", sa.BigInteger()),
        sa.Column("market_ref_rial", sa.BigInteger()),
        sa.Column("market_ref_observation_id", sa.Uuid()),
        sa.Column("median_rial", sa.BigInteger()),
        sa.Column("qualifying_count", sa.Integer(), nullable=False),
        _uuids("qualifying_observation_ids"),
        _uuids("excluded_outlier_ids"),
        sa.Column("effective_cost_rial", sa.BigInteger()),
        sa.Column("profit_current_rial", sa.BigInteger()),
        sa.Column("profit_suggested_rial", sa.BigInteger()),
        sa.Column("explanation", sa.Text(), nullable=False),
        _uuids("observation_ids"),
        _uuids("match_version_ids"),
        _uuids("outlier_confirmation_ids"),
        sa.Column("cost_record_id", sa.Uuid()),
        _uuids("cost_component_ids"),
        _uuids("rule_version_ids"),
        sa.Column("inputs", JSONB(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        # Deferred: the old row points at its successor before the successor is inserted, so
        # "one current recommendation per variant" holds at every statement.
        sa.Column(
            "superseded_by",
            sa.Uuid(),
            sa.ForeignKey("recommendation.id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "outcome IN ('increase', 'decrease', 'hold', 'insufficient_data', 'floor_conflict')",
            name="outcome",
        ),
        sa.CheckConstraint(
            "(outcome IN ('increase', 'decrease')) = (suggested_price_rial IS NOT NULL)",
            name="suggestion_only_when_actionable",
        ),
        sa.CheckConstraint(
            "suggested_price_rial IS NULL OR suggested_price_rial >= floor_rial",
            name="never_below_floor",
        ),
    )
    op.create_index(
        "uq_recommendation_current",
        "recommendation",
        ["variant_id"],
        unique=True,
        postgresql_where=sa.text("superseded_by IS NULL"),
    )
    op.create_index(
        "ix_recommendation_tenant_created", "recommendation", ["tenant_id", "created_at"]
    )
    enable_tenant_rls("recommendation")
    grant_append_only("recommendation")
    op.execute(f"GRANT UPDATE (superseded_by, superseded_at) ON recommendation TO {app_role()}")
    grant("recommendation", ["SELECT"], maintenance_role())

    op.create_table(
        "outlier_confirmation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "observation_id",
            sa.Uuid(),
            sa.ForeignKey("observation.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("observation_id", name="uq_outlier_confirmation_observation"),
    )
    enable_tenant_rls("outlier_confirmation")
    grant_append_only("outlier_confirmation")
    grant("outlier_confirmation", ["SELECT", "DELETE"], maintenance_role())


def downgrade() -> None:
    op.drop_table("outlier_confirmation")
    op.drop_table("recommendation")
