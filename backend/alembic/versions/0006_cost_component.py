"""Fixed per-unit cost components.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import app_role, enable_tenant_rls, grant

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cost_component",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deactivated_by", sa.Text()),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_rial >= 0", name="non_negative"),
    )
    enable_tenant_rls("cost_component")
    grant("cost_component", ["SELECT", "INSERT"])
    op.execute(
        f"GRANT UPDATE (active, deactivated_by, deactivated_at) ON cost_component TO {app_role()}"
    )


def downgrade() -> None:
    op.drop_table("cost_component")
