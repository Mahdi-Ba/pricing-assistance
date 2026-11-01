"""Alembic environment. Migrations run as the schema owner role (PA_DATABASE_OWNER_URL)."""

from alembic import context
from sqlalchemy import create_engine, pool

from pricing_assistant.core.settings import get_settings

config = context.config


def run_migrations_online() -> None:
    url = config.attributes.get("url") or get_settings().database_owner_url.get_secret_value()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run against a database.")
run_migrations_online()
