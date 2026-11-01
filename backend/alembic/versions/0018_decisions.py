"""Expert decisions, below-floor override reviews and outcome stages (append-only).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import enable_tenant_rls, grant_append_only

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column(
            "recommendation_id", sa.Uuid(), sa.ForeignKey("recommendation.id"), nullable=False
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("applied_price_rial", sa.BigInteger()),
        sa.Column("floor_rial", sa.BigInteger()),  # floor in force when the decision was made
        sa.Column("below_floor_override", sa.Boolean(), nullable=False),
        sa.Column("override_reason", sa.Text()),
        sa.Column("supersedes_decision_id", sa.Uuid(), sa.ForeignKey("decision.id")),
        sa.Column("actor_subject", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("type IN ('accept', 'accept_modified', 'reject', 'defer')", name="type"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_required"),
        sa.CheckConstraint(
            "(type IN ('accept', 'accept_modified')) = (applied_price_rial IS NOT NULL)",
            name="applied_price_for_accept_only",
        ),
        sa.CheckConstraint(
            "applied_price_rial IS NULL OR applied_price_rial > 0", name="applied_price_positive"
        ),
        sa.CheckConstraint(
            "below_floor_override = (floor_rial IS NOT NULL AND applied_price_rial IS NOT NULL "
            "AND applied_price_rial < floor_rial)",
            name="override_flag_matches_floor",
        ),
        sa.CheckConstraint(
            "NOT below_floor_override OR length(btrim(coalesce(override_reason, ''))) > 0",
            name="override_reason_required",
        ),
    )
    op.create_index("ix_decision_variant_created", "decision", ["variant_id", "created_at"])
    op.create_index("ix_decision_recommendation", "decision", ["recommendation_id"])
    op.create_index(
        "uq_decision_supersedes",
        "decision",
        ["supersedes_decision_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_decision_id IS NOT NULL"),
    )
    enable_tenant_rls("decision")
    grant_append_only("decision")

    op.create_table(
        "override_review",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("decision_id", sa.Uuid(), sa.ForeignKey("decision.id"), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_subject", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("verdict IN ('approved', 'rejected', 'self_approved')", name="verdict"),
        sa.CheckConstraint("length(btrim(reason)) > 0", name="reason_required"),
        sa.UniqueConstraint("decision_id", name="uq_override_review_decision"),  # final verdict
    )
    enable_tenant_rls("override_review")
    grant_append_only("override_review")

    op.create_table(
        "decision_outcome",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("decision_id", sa.Uuid(), sa.ForeignKey("decision.id"), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.Text()),  # reported_done
        sa.Column("observation_id", sa.Uuid()),  # observed_on_site / reflected_in_channel
        sa.Column("delay_seconds", sa.Integer()),  # since reported_done
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "stage IN ('reported_done', 'observed_on_site', 'reflected_in_channel', "
            "'verification_overdue')",
            name="stage",
        ),
        sa.CheckConstraint(
            "stage <> 'reported_done' OR actor IS NOT NULL", name="reported_done_has_actor"
        ),
        sa.CheckConstraint(
            "stage NOT IN ('observed_on_site', 'reflected_in_channel') "
            "OR observation_id IS NOT NULL",
            name="observed_has_evidence",
        ),
        sa.UniqueConstraint("decision_id", "stage", name="uq_decision_outcome_stage"),
    )
    enable_tenant_rls("decision_outcome")
    grant_append_only("decision_outcome")


def downgrade() -> None:
    op.drop_table("decision_outcome")
    op.drop_table("override_review")
    op.drop_table("decision")
