"""Helpers for hand-written Alembic migrations: tenant RLS policies and explicit grants.

Every tenant-owned table must call :func:`enable_tenant_rls` and grant only the privileges the
application role needs. Append-only tables are granted ``SELECT, INSERT`` and nothing else.
"""

import re
from collections.abc import Iterable

from alembic import op

from pricing_assistant.core.settings import get_settings

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})


def _ident(name: str) -> str:
    if not _IDENTIFIER.fullmatch(name):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return name


def app_role() -> str:
    return _ident(get_settings().database_app_role)


def maintenance_role() -> str:
    return _ident(get_settings().database_maintenance_role)


def enable_tenant_rls(table: str, *, tenant_column: str = "tenant_id") -> None:
    """Enable and force RLS so every role, including the owner, only sees the current tenant."""
    table, column = _ident(table), _ident(tenant_column)
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({column} = pa_current_tenant()) "
        f"WITH CHECK ({column} = pa_current_tenant())"
    )


def disable_tenant_rls(table: str) -> None:
    table = _ident(table)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def grant(table: str, privileges: Iterable[str], role: str | None = None) -> None:
    privs = sorted({p.upper() for p in privileges})
    unknown = set(privs) - _PRIVILEGES
    if unknown or not privs:
        raise ValueError(f"invalid privileges: {privs}")
    op.execute(f"GRANT {', '.join(privs)} ON {_ident(table)} TO {_ident(role or app_role())}")


def grant_append_only(table: str) -> None:
    """Application role may read and insert, never update or delete."""
    grant(table, ["SELECT", "INSERT"])
