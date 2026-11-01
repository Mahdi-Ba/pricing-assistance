"""LLM call log and the optional reworded explanation of a recommendation.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import (
    app_role,
    enable_tenant_rls,
    grant_append_only,
)

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_call",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "result IN ('ok', 'invalid', 'error', 'budget_exhausted')", name="result"
        ),
    )
    op.create_index("ix_llm_call_tenant_created", "llm_call", ["tenant_id", "created_at"])
    enable_tenant_rls("llm_call")
    grant_append_only("llm_call")

    op.add_column("recommendation", sa.Column("explanation_llm", sa.Text()))
    op.execute(f"GRANT UPDATE (explanation_llm) ON recommendation TO {app_role()}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE (explanation_llm) ON recommendation FROM {app_role()}")
    op.drop_column("recommendation", "explanation_llm")
    op.drop_table("llm_call")
