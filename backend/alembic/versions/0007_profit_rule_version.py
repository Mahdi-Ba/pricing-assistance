"""Versioned profit rules.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from pricing_assistant.core.migration_helpers import enable_tenant_rls, grant_append_only

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profit_rule_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("scope_key", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("min_margin_bp", sa.Integer()),
        sa.Column("fee_rate_bp", sa.Integer()),
        sa.Column("vat_rate_bp", sa.Integer()),
        sa.Column("ceiling_rial", sa.BigInteger()),
        sa.Column("undercut_step_rial", sa.BigInteger()),
        sa.Column("hold_tolerance_bp", sa.Integer()),
        sa.Column("rounding_step_rial", sa.BigInteger()),
        sa.Column("max_data_age_a_seconds", sa.Integer()),
        sa.Column("max_data_age_b_seconds", sa.Integer()),
        sa.Column("max_data_age_c_seconds", sa.Integer()),
        sa.Column("outlier_threshold_bp", sa.Integer()),
        sa.Column("min_qualifying_offers", sa.Integer()),
        sa.Column("competitor_set", JSONB()),
        sa.Column("reason", sa.Text()),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("scope IN ('default', 'category', 'variant')", name="scope"),
        sa.CheckConstraint(
            "(scope = 'default') = (scope_key IS NULL)", name="scope_key_matches_scope"
        ),
        sa.CheckConstraint(
            "min_margin_bp IS NULL OR fee_rate_bp IS NULL OR min_margin_bp + fee_rate_bp < 10000",
            name="margin_plus_fee",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "scope",
            "scope_key",
            "version",
            name="uq_profit_rule_version",
            postgresql_nulls_not_distinct=True,
        ),
    )
    enable_tenant_rls("profit_rule_version")
    grant_append_only("profit_rule_version")


def downgrade() -> None:
    op.drop_table("profit_rule_version")
