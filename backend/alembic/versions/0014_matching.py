"""Matching: versioned offer_attributes, append-only match_version, rejected_pair.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from pricing_assistant.core.migration_helpers import app_role, enable_tenant_rls, grant_append_only

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "offer_attributes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), nullable=False),
        sa.Column("seller_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attributes", JSONB(), nullable=False),
        sa.Column("attributes_hash", sa.Text(), nullable=False),
        sa.Column("observation_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tracked_offer_id", "seller_key", "version", name="uq_offer_attributes_version"
        ),
    )
    enable_tenant_rls("offer_attributes")
    grant_append_only("offer_attributes")

    op.create_table(
        "match_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), nullable=False),
        sa.Column("seller_key", sa.Text(), nullable=False),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("flags", JSONB(), nullable=False, server_default="[]"),
        sa.Column("confidence_bp", sa.Integer(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("attributes_id", sa.Uuid(), sa.ForeignKey("offer_attributes.id")),
        sa.Column("attributes_hash", sa.Text(), nullable=False),
        sa.Column("previous_version_id", sa.Uuid(), sa.ForeignKey("match_version.id")),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "state IN ('proposed', 'confirmed', 'rejected', 'needs_review')", name="state"
        ),
        sa.CheckConstraint("decided_by IN ('rule', 'llm', 'human')", name="decided_by"),
        sa.CheckConstraint("confidence_bp BETWEEN 0 AND 10000", name="confidence"),
        sa.CheckConstraint(
            "decided_by = 'human' OR state <> 'confirmed' OR "
            "(decided_by = 'rule' AND flags = '[]'::jsonb)",
            name="llm_never_confirms",
        ),
    )
    op.create_index(
        "uq_match_version_current",
        "match_version",
        ["tracked_offer_id", "seller_key"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index("ix_match_version_variant", "match_version", ["variant_id", "is_current"])
    enable_tenant_rls("match_version")
    grant_append_only("match_version")
    op.execute(f"GRANT UPDATE (is_current) ON match_version TO {app_role()}")

    op.create_table(
        "rejected_pair",
        sa.Column(
            "tracked_offer_id", sa.Uuid(), sa.ForeignKey("tracked_offer.id"), primary_key=True
        ),
        sa.Column("seller_key", sa.Text(), primary_key=True),
        sa.Column("variant_id", sa.Uuid(), sa.ForeignKey("variant.id"), primary_key=True),
        sa.Column("attributes_hash", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("match_version_id", sa.Uuid(), sa.ForeignKey("match_version.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    enable_tenant_rls("rejected_pair")
    grant_append_only("rejected_pair")


def downgrade() -> None:
    op.drop_table("rejected_pair")
    op.drop_table("match_version")
    op.drop_table("offer_attributes")
