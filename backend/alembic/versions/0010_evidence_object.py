"""Evidence snapshot registry.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import (
    app_role,
    enable_tenant_rls,
    grant,
    maintenance_role,
)

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_object",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False, unique=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('html', 'extracted', 'screenshot')", name="kind"),
    )
    op.create_index("ix_evidence_object_created", "evidence_object", ["tenant_id", "created_at"])
    enable_tenant_rls("evidence_object")
    grant("evidence_object", ["SELECT", "INSERT"])
    for role in (app_role(), maintenance_role()):
        op.execute(f"GRANT UPDATE (expired_at) ON evidence_object TO {role}")
    grant("evidence_object", ["SELECT"], maintenance_role())


def downgrade() -> None:
    op.drop_table("evidence_object")
