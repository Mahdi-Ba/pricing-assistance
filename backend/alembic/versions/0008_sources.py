"""Source registry: source, source_clearance, connector config and secrets,
extraction_rule_version and tracked_offer.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from pricing_assistant.core.migration_helpers import (
    app_role,
    enable_tenant_rls,
    grant,
    grant_append_only,
)

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column[datetime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "source",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_domain", sa.Text(), nullable=False),
        sa.Column("connector_key", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("currency_unit", sa.Text(), nullable=False),
        sa.Column("quota_per_minute", sa.Integer(), nullable=False),
        sa.Column("interval_a_seconds", sa.Integer(), nullable=False),
        sa.Column("interval_b_seconds", sa.Integer(), nullable=False),
        sa.Column("interval_c_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="candidate"),
        sa.Column("status_reason", sa.Text()),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_source_name"),
        sa.CheckConstraint("method IN ('api', 'html', 'rendered_page')", name="method"),
        sa.CheckConstraint("currency_unit IN ('RIAL', 'TOMAN')", name="currency_unit"),
        sa.CheckConstraint(
            "status IN ('candidate', 'under_evaluation', 'approved', 'suspended', 'rejected')",
            name="status",
        ),
        sa.CheckConstraint("quota_per_minute > 0", name="quota"),
        sa.CheckConstraint(
            "interval_a_seconds > 0 AND interval_b_seconds > 0 AND interval_c_seconds > 0",
            name="intervals",
        ),
    )
    enable_tenant_rls("source")
    grant("source", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "source_clearance",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("approver_name", sa.Text()),
        sa.Column("approved_on", sa.Date()),
        sa.Column("scope", sa.Text()),
        sa.Column("reference", sa.Text()),
        sa.Column("permitted_requests_per_minute", sa.Integer()),
        sa.Column("reason", sa.Text()),
        sa.Column("recorded_by", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint("kind IN ('granted', 'revoked')", name="kind"),
        sa.CheckConstraint(
            "kind <> 'granted' OR (approver_name IS NOT NULL AND approved_on IS NOT NULL "
            "AND scope IS NOT NULL AND reference IS NOT NULL "
            "AND permitted_requests_per_minute > 0)",
            name="grant_complete",
        ),
        sa.CheckConstraint("kind <> 'revoked' OR reason IS NOT NULL", name="revoke_reason"),
    )
    op.create_index("ix_source_clearance_source", "source_clearance", ["source_id", "created_at"])
    enable_tenant_rls("source_clearance")
    grant_append_only("source_clearance")

    op.create_table(
        "connector_config",
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    enable_tenant_rls("connector_config")
    grant("connector_config", ["SELECT", "INSERT", "UPDATE"])

    op.create_table(
        "connector_secret",
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), primary_key=True),
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    enable_tenant_rls("connector_secret")
    grant("connector_secret", ["SELECT", "INSERT", "UPDATE", "DELETE"])

    op.create_table(
        "extraction_rule_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("validation", JSONB()),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created(),
        sa.Column("reviewed_by", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_reason", sa.Text()),
        sa.UniqueConstraint("source_id", "version", name="uq_extraction_rule_version"),
        sa.CheckConstraint("state IN ('proposed', 'active', 'retired', 'rejected')", name="state"),
        sa.CheckConstraint("origin IN ('admin', 'llm')", name="origin"),
    )
    op.create_index(
        "uq_extraction_rule_one_active",
        "extraction_rule_version",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    enable_tenant_rls("extraction_rule_version")
    grant("extraction_rule_version", ["SELECT", "INSERT"])
    op.execute(
        "GRANT UPDATE (state, reviewed_by, reviewed_at, review_reason) "
        f"ON extraction_rule_version TO {app_role()}"
    )

    op.create_table(
        "tracked_offer",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_own_store", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_own_channel", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_due_at", sa.DateTime(timezone=True)),
        sa.Column("suggested_by", sa.Text()),
        sa.Column("suggestion_rationale", sa.Text()),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created(),
        sa.Column("confirmed_by", sa.Text()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "source_id", "url", "variant_id", name="uq_tracked_offer"),
        sa.CheckConstraint(
            "status IN ('suggested', 'active', 'dismissed', 'paused')", name="status"
        ),
        sa.CheckConstraint("NOT (is_own_store AND is_own_channel)", name="own_flags"),
        sa.CheckConstraint("status <> 'active' OR next_due_at IS NOT NULL", name="active_due"),
    )
    op.create_index(
        "ix_tracked_offer_due",
        "tracked_offer",
        ["tenant_id", "next_due_at"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_tracked_offer_variant", "tracked_offer", ["variant_id"])
    enable_tenant_rls("tracked_offer")
    grant("tracked_offer", ["SELECT", "INSERT", "UPDATE"])


def downgrade() -> None:
    op.drop_table("tracked_offer")
    op.drop_table("extraction_rule_version")
    op.drop_table("connector_secret")
    op.drop_table("connector_config")
    op.drop_table("source_clearance")
    op.drop_table("source")
