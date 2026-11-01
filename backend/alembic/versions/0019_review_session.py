"""Review sessions for the review-time KPI.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import app_role, enable_tenant_rls, grant

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_session",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), sa.ForeignKey("recommendation.id")),
        sa.Column("user_subject", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("close_reason", sa.Text()),
        sa.Column("decision_id", sa.Uuid(), sa.ForeignKey("decision.id")),
        sa.CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('decision', 'left', 'idle')",
            name="close_reason",
        ),
        sa.CheckConstraint(
            "(closed_at IS NULL) = (close_reason IS NULL)", name="closed_with_reason"
        ),
        sa.CheckConstraint("closed_at IS NULL OR closed_at >= opened_at", name="closed_after_open"),
    )
    op.create_index(
        "ix_review_session_open",
        "review_session",
        ["last_activity_at"],
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    enable_tenant_rls("review_session")
    grant("review_session", ["SELECT", "INSERT"])
    op.execute(
        "GRANT UPDATE (last_activity_at, closed_at, close_reason, decision_id) "
        f"ON review_session TO {app_role()}"
    )


def downgrade() -> None:
    op.drop_table("review_session")
