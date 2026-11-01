"""Transactional outbox and consumer deduplication tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from pricing_assistant.core.migration_helpers import (
    app_role,
    enable_tenant_rls,
    grant,
    grant_append_only,
)

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("causation_id", sa.Uuid()),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_outbox_event_pending",
        "outbox_event",
        ["tenant_id", "occurred_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )
    enable_tenant_rls("outbox_event")
    grant("outbox_event", ["SELECT", "INSERT"])
    # The relay may only mark events dispatched; payloads are immutable.
    op.execute(f"GRANT UPDATE (dispatched_at, attempts) ON outbox_event TO {app_role()}")

    op.create_table(
        "processed_event",
        sa.Column("consumer", sa.Text(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    enable_tenant_rls("processed_event")
    grant_append_only("processed_event")


def downgrade() -> None:
    op.drop_table("processed_event")
    op.drop_table("outbox_event")
