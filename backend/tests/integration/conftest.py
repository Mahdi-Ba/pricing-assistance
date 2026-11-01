"""Fixtures for integration tests against the local stack (``make up``)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from pricing_assistant.core.db import Database
from pricing_assistant.core.db import create_engine as create_async_engine
from pricing_assistant.core.settings import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
TENANT_A = uuid.UUID("0192f0a0-0000-7000-8000-000000000001")
TENANT_B = uuid.UUID("0192f0a0-0000-7000-8000-000000000002")


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["url"] = get_settings().database_owner_url.get_secret_value()
    return config


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    engine = create_engine(get_settings().database_owner_url.get_secret_value(), poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated(owner_engine: Engine) -> None:
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def truncate_all(owner_engine: Engine) -> None:
    with owner_engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        ).scalars()
        names = ", ".join(tables)
        if names:
            conn.execute(text(f"TRUNCATE {names} CASCADE"))


def create_tenant(owner_engine: Engine, tenant_id: uuid.UUID, name: str) -> None:
    with owner_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        conn.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, :name)"),
            {"id": tenant_id, "name": name},
        )


@pytest.fixture
def clean_db(migrated: None, owner_engine: Engine) -> None:
    truncate_all(owner_engine)
    create_tenant(owner_engine, TENANT_A, "Pilot store")
    create_tenant(owner_engine, TENANT_B, "Sandbox store")


@pytest.fixture
async def db(clean_db: None) -> AsyncIterator[Database]:
    database = Database(create_async_engine(get_settings().database_app_url, pool_size=2))
    yield database
    await database.dispose()


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(get_settings().redis_url.get_secret_value(), decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def maintenance_db(clean_db: None) -> AsyncIterator[Database]:
    database = Database(create_async_engine(get_settings().database_maintenance_url, pool_size=1))
    yield database
    await database.dispose()
