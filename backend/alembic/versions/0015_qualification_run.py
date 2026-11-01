"""Source qualification runs.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from pricing_assistant.core.migration_helpers import app_role, enable_tenant_rls, grant

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "qualification_run",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("variant_ids", ARRAY(sa.Uuid()), nullable=False),
        sa.Column("source_ids", ARRAY(sa.Uuid()), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_offers", sa.Integer(), nullable=False),
        sa.Column("report", JSONB()),
        sa.Column("started_by", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running', 'completed')", name="status"),
    )
    enable_tenant_rls("qualification_run")
    grant("qualification_run", ["SELECT", "INSERT"])
    op.execute(f"GRANT UPDATE (status, report, completed_at) ON qualification_run TO {app_role()}")


def downgrade() -> None:
    op.drop_table("qualification_run")
