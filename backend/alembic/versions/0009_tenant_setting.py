"""Per-tenant operational settings.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from pricing_assistant.core.migration_helpers import enable_tenant_rls, grant

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_setting",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), primary_key=True),
        sa.Column("values", JSONB(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    enable_tenant_rls("tenant_setting")
    grant("tenant_setting", ["SELECT", "INSERT", "UPDATE"])


def downgrade() -> None:
    op.drop_table("tenant_setting")
