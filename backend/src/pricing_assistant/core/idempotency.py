"""``Idempotency-Key`` support for state-changing commands (design D10).

Routers that use :class:`IdempotentRoute` accept an optional ``Idempotency-Key`` header on
POST/PUT/PATCH/DELETE. The first request claims the key for the caller's tenant; its final
response (status < 500) is stored for ``idempotency_ttl_hours`` and replayed verbatim for
retries with the same key and payload. A different payload with the same key is rejected, and
a concurrent duplicate while the first is still running gets 409.
"""

import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import DateTime, ForeignKey, Integer, Text, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column
from starlette.datastructures import UploadFile as StarletteUploadFile

from pricing_assistant.core.db import Base, Database
from pricing_assistant.core.errors import Conflict, ValidationFailed
from pricing_assistant.core.settings import Settings

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotency-Replayed"
COMMAND_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_KEY = re.compile(r"^[\x21-\x7e]{8,255}$")
_SERVER_ERROR = 500
_STORED_HEADERS = ("content-type", "location")

TenantResolver = Callable[[Request], Awaitable[uuid.UUID]]


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_record"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


async def _request_hash(request: Request) -> str:
    """Hash of the request's meaning. Multipart bodies are hashed by field name and content,
    because clients pick a new random boundary for every attempt."""
    digest = hashlib.sha256()
    digest.update(request.method.encode())
    digest.update(b"\0")
    digest.update(request.url.path.encode())
    digest.update(b"\0")
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()  # cached by Starlette; the endpoint reuses it
        for name, value in sorted(form.multi_items(), key=lambda item: item[0]):
            digest.update(name.encode())
            digest.update(b"=")
            if isinstance(value, StarletteUploadFile):
                content = await value.read()
                await value.seek(0)
                digest.update(hashlib.sha256(content).digest())
            else:
                digest.update(value.encode())
            digest.update(b"\0")
    else:
        digest.update(await request.body())
    return digest.hexdigest()


async def _claim(
    db: Database, tenant_id: uuid.UUID, key: str, request_hash: str, ttl: timedelta
) -> IdempotencyRecordRow | None:
    """Claim ``key``; return the existing record if another request already holds it."""
    async with db.tenant_session(tenant_id) as session:
        existing = await session.get(IdempotencyRecordRow, (tenant_id, key), with_for_update=True)
        if existing is not None and existing.created_at < datetime.now(UTC) - ttl:
            await session.delete(existing)
            await session.flush()
            existing = None
        if existing is not None:
            return existing
        claimed = await session.scalar(
            insert(IdempotencyRecordRow)
            .values(tenant_id=tenant_id, key=key, request_hash=request_hash)
            .on_conflict_do_nothing()
            .returning(IdempotencyRecordRow.key)
        )
        if claimed is None:  # lost a race with a concurrent first request
            return await session.get(IdempotencyRecordRow, (tenant_id, key))
    return None


async def _complete(db: Database, tenant_id: uuid.UUID, key: str, response: Response) -> None:
    async with db.tenant_session(tenant_id) as session:
        record = await session.get(IdempotencyRecordRow, (tenant_id, key), with_for_update=True)
        if record is None:
            return
        record.status_code = response.status_code
        record.response_body = bytes(response.body).decode("utf-8")
        record.content_type = response.headers.get("content-type")
        record.location = response.headers.get("location")
        record.completed_at = datetime.now(UTC)


async def _release(db: Database, tenant_id: uuid.UUID, key: str) -> None:
    async with db.tenant_session(tenant_id) as session:
        await session.execute(
            delete(IdempotencyRecordRow).where(
                IdempotencyRecordRow.tenant_id == tenant_id,
                IdempotencyRecordRow.key == key,
                IdempotencyRecordRow.completed_at.is_(None),
            )
        )


def _replay(record: IdempotencyRecordRow) -> Response:
    headers = {REPLAYED_HEADER: "true"}
    if record.location:
        headers["Location"] = record.location
    return Response(
        content=record.response_body or "",
        status_code=record.status_code or 200,
        media_type=record.content_type,
        headers=headers,
    )


class IdempotentRoute(APIRoute):
    """APIRoute that applies ``Idempotency-Key`` semantics to command methods."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            key = request.headers.get(HEADER)
            if key is None or request.method not in COMMAND_METHODS:
                return await original(request)
            if not _KEY.fullmatch(key):
                raise ValidationFailed(
                    "Idempotency-Key must be 8-255 visible ASCII characters",
                    code="invalid_idempotency_key",
                )
            db: Database = request.app.state.db
            settings: Settings = request.app.state.settings
            resolve_tenant: TenantResolver = request.app.state.resolve_tenant
            tenant_id = await resolve_tenant(request)
            request_hash = await _request_hash(request)
            ttl = timedelta(hours=settings.idempotency_ttl_hours)

            existing = await _claim(db, tenant_id, key, request_hash, ttl)
            if existing is not None:
                if existing.completed_at is None:
                    raise Conflict(
                        "A request with this Idempotency-Key is still being processed",
                        code="idempotency_in_progress",
                        message_fa="درخواست قبلی هنوز در حال پردازش است.",
                    )
                if existing.request_hash != request_hash:
                    raise ValidationFailed(
                        "Idempotency-Key was already used with a different request",
                        code="idempotency_key_reused",
                        message_fa="این کلید تکرار برای درخواست دیگری استفاده شده است.",
                    )
                return _replay(existing)

            try:
                response = await original(request)
            except BaseException:
                await _release(db, tenant_id, key)
                raise
            if response.status_code >= _SERVER_ERROR or not hasattr(response, "body"):
                await _release(db, tenant_id, key)
            else:
                await _complete(db, tenant_id, key, response)
            return response

        return handler


async def purge_expired(db: Database, tenant_id: uuid.UUID, ttl: timedelta) -> int:
    async with db.tenant_session(tenant_id) as session:
        result = await session.scalars(
            delete(IdempotencyRecordRow)
            .where(IdempotencyRecordRow.created_at < datetime.now(UTC) - ttl)
            .returning(IdempotencyRecordRow.key)
        )
        return len(result.all())


__all__ = ["HEADER", "REPLAYED_HEADER", "IdempotentRoute", "TenantResolver", "purge_expired"]
