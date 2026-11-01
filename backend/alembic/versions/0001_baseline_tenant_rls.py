"""Baseline: schema privileges, tenant table and RLS helpers.

Revision ID: 0001
Revises:
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from pricing_assistant.core.migration_helpers import app_role, grant, maintenance_role

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    app, maintenance = app_role(), maintenance_role()
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {app}, {maintenance}")

    # The tenant of the current transaction; NULL when unset, so policies match no rows.
    op.execute(
        """
        CREATE FUNCTION pa_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE AS
        $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$
        """
    )

    op.create_table(
        "tenant",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="status"),
    )
    op.execute("ALTER TABLE tenant ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON tenant USING (id = pa_current_tenant())")
    grant("tenant", ["SELECT"])

    # Lets background processes iterate tenants without bypassing RLS on business tables.
    op.execute(
        """
        CREATE FUNCTION pa_active_tenant_ids() RETURNS TABLE (id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
        $$ SELECT t.id FROM tenant t WHERE t.status = 'active' ORDER BY t.id $$
        """
    )
    # SECURITY DEFINER runs as the owner, which is also subject to FORCE RLS on tenant;
    # this dedicated policy lets the function (and only the owner) enumerate tenants.
    op.execute("CREATE POLICY owner_enumerate ON tenant FOR SELECT TO CURRENT_USER USING (true)")
    op.execute("REVOKE ALL ON FUNCTION pa_active_tenant_ids() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION pa_active_tenant_ids() TO {app}, {maintenance}")
    op.execute(f"GRANT EXECUTE ON FUNCTION pa_current_tenant() TO {app}, {maintenance}")


def downgrade() -> None:
    op.execute("DROP FUNCTION pa_active_tenant_ids()")
    op.drop_table("tenant")
    op.execute("DROP FUNCTION pa_current_tenant()")
    app, maintenance = app_role(), maintenance_role()
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {app}, {maintenance}")
