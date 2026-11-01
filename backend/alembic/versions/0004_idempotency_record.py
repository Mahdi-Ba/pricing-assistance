"""Idempotency-Key records for command replay.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import app_role, enable_tenant_rls, grant

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_record",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), primary_key=True),
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("response_body", sa.Text()),
        sa.Column("content_type", sa.Text()),
        sa.Column("location", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_idempotency_record_created_at", "idempotency_record", ["created_at"])
    enable_tenant_rls("idempotency_record")
    # A replay cache, not a record of business facts: expired or failed claims are deleted.
    grant("idempotency_record", ["SELECT", "INSERT", "DELETE"])
    op.execute(
        "GRANT UPDATE (status_code, response_body, content_type, location, completed_at) "
        f"ON idempotency_record TO {app_role()}"
    )


def downgrade() -> None:
    op.drop_table("idempotency_record")
