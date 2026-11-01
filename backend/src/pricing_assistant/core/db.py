"""Async persistence: declarative base, engine factory and tenant-scoped sessions.

Every business query runs in a transaction that sets ``app.tenant_id`` first. PostgreSQL RLS
policies (see ``migration_helpers.enable_tenant_rls``) then restrict all reads and writes to
that tenant, so isolation does not depend on application code remembering a WHERE clause.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from pydantic import SecretStr
from sqlalchemy import DateTime, MetaData, Text, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantRow(Base):
    """A customer store. Every business row references exactly one tenant."""

    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantScoped:
    """Mixin for tenant-owned rows. The RLS policy compares this column with the session."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def create_engine(url: SecretStr, *, pool_size: int = 10) -> AsyncEngine:
    return create_async_engine(
        url.get_secret_value(),
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


class Database:
    """Owns the engine and hands out transaction-bound, tenant-scoped sessions."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    @asynccontextmanager
    async def tenant_session(self, tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
        """Open a transaction scoped to ``tenant_id``; commit on success, roll back on error."""
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(tenant_id)},
            )
            yield session

    @asynccontextmanager
    async def system_session(self) -> AsyncIterator[AsyncSession]:
        """Transaction without a tenant. RLS hides all tenant rows; use only for
        SECURITY DEFINER functions such as ``pa_active_tenant_ids()``."""
        async with self._sessions() as session, session.begin():
            yield session

    async def active_tenant_ids(self) -> list[uuid.UUID]:
        async with self.system_session() as session:
            result = await session.execute(text("SELECT id FROM pa_active_tenant_ids()"))
            return [row[0] for row in result]

    async def dispose(self) -> None:
        await self.engine.dispose()
