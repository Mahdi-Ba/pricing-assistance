"""Allow deleting a source that was never used.

The application may delete a ``source`` row only through ``sources.registry.delete_source``,
which accepts candidates without clearances, offers or any collected data. Every table that
references ``source`` keeps its foreign key without cascade, so the database refuses to delete
a source that is in use even if the service check were bypassed.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

from pricing_assistant.core.migration_helpers import app_role, grant

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    grant("source", ["DELETE"])


def downgrade() -> None:
    op.execute(f'REVOKE DELETE ON source FROM "{app_role()}"')
