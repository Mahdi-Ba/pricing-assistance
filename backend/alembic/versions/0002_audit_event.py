"""Append-only audit_event table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from pricing_assistant.core.migration_helpers import enable_tenant_rls, grant_append_only

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("actor_subject", sa.Text(), nullable=False),
        sa.Column("actor_username", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text()),
        sa.Column("before", JSONB()),
        sa.Column("after", JSONB()),
        sa.Column("reason", sa.Text()),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.CheckConstraint("outcome IN ('success', 'denied')", name="outcome"),
    )
    op.create_index("ix_audit_event_tenant_id", "audit_event", ["tenant_id"])
    op.create_index("ix_audit_event_action", "audit_event", ["action"])
    op.create_index("ix_audit_event_correlation_id", "audit_event", ["correlation_id"])
    op.create_index("ix_audit_event_target", "audit_event", ["target_type", "target_id"])
    enable_tenant_rls("audit_event")
    grant_append_only("audit_event")


def downgrade() -> None:
    op.drop_table("audit_event")
