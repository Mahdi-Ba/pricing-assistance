"""Retention purge log and maintenance-role grants.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import enable_tenant_rls, grant, maintenance_role

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purge_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_count", sa.Integer(), nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind IN ('evidence', 'observation')", name="kind"),
    )
    enable_tenant_rls("purge_log")
    grant("purge_log", ["SELECT"])
    maintenance = maintenance_role()
    grant("purge_log", ["SELECT", "INSERT"], maintenance)
    grant("tenant_setting", ["SELECT"], maintenance)
    grant("audit_event", ["SELECT", "INSERT"], maintenance)


def downgrade() -> None:
    op.drop_table("purge_log")
