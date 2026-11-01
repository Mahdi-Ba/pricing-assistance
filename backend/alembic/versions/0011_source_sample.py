"""Sample pages used to validate extraction rules.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import enable_tenant_rls, grant_append_only

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_sample",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("source.id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("html_gzip", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_source_sample_source", "source_sample", ["source_id"])
    enable_tenant_rls("source_sample")
    grant_append_only("source_sample")


def downgrade() -> None:
    op.drop_table("source_sample")
