"""Match audit samples and review-time baselines.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import (
    app_role,
    enable_tenant_rls,
    grant,
    grant_append_only,
)

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_audit_sample",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),  # YYYY-MM
        sa.Column("population", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="period_format"),
        sa.CheckConstraint("size >= 0 AND size <= population", name="size"),
    )
    enable_tenant_rls("match_audit_sample")
    grant_append_only("match_audit_sample")

    op.create_table(
        "match_audit_item",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("sample_id", sa.Uuid(), sa.ForeignKey("match_audit_sample.id"), nullable=False),
        sa.Column("match_version_id", sa.Uuid(), sa.ForeignKey("match_version.id"), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("confidence_band", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text()),
        sa.Column("note", sa.Text()),
        sa.Column("reviewed_by", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('correct', 'incorrect')", name="verdict"
        ),
        sa.CheckConstraint(
            "(verdict IS NULL) = (reviewed_by IS NULL)", name="verdict_has_reviewer"
        ),
        sa.UniqueConstraint("sample_id", "match_version_id", name="uq_audit_item_match"),
    )
    enable_tenant_rls("match_audit_item")
    grant("match_audit_item", ["SELECT", "INSERT"])
    op.execute(
        "GRANT UPDATE (verdict, note, reviewed_by, reviewed_at) "
        f"ON match_audit_item TO {app_role()}"
    )

    op.create_table(
        "review_baseline",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("median_seconds", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("entered_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("median_seconds > 0", name="positive"),
    )
    op.create_index("ix_review_baseline_category", "review_baseline", ["category", "created_at"])
    enable_tenant_rls("review_baseline")
    grant_append_only("review_baseline")


def downgrade() -> None:
    op.drop_table("review_baseline")
    op.drop_table("match_audit_item")
    op.drop_table("match_audit_sample")
