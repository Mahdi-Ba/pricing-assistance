"""Evidence snapshots in S3-compatible storage (design D12, task 4.8).

Objects are keyed ``{tenant}/{source}/{offer}/{observed_at}.{ext}``: gzipped HTML, the
extracted JSON and, for rendered pages, a PNG screenshot. Each object is registered in
``evidence_object`` (tenant-scoped by RLS); the UI gets a short-lived presigned URL only after
the caller's tenant session can see that row, so another tenant's evidence returns 404.
"""

import asyncio
import gzip
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base
from pricing_assistant.core.errors import NotFound
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.settings import Settings
from pricing_assistant.sources.api import Evidence


class EvidenceKind(StrEnum):
    HTML = "html"
    EXTRACTED = "extracted"
    SCREENSHOT = "screenshot"


_FORMAT = {
    EvidenceKind.HTML: ("html.gz", "text/html; charset=utf-8", "gzip"),
    EvidenceKind.EXTRACTED: ("json", "application/json", None),
    EvidenceKind.SCREENSHOT: ("png", "image/png", None),
}


class EvidenceObjectRow(Base):
    __tablename__ = "evidence_object"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracked_offer.id"))
    kind: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True, slots=True)
class StoredObject:
    kind: EvidenceKind
    key: str
    content_type: str
    size_bytes: int
    sha256: str


def object_key(
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    tracked_offer_id: uuid.UUID,
    observed_at: datetime,
    kind: EvidenceKind,
) -> str:
    stamp = observed_at.strftime("%Y%m%dT%H%M%S%fZ")
    return f"{tenant_id}/{source_id}/{tracked_offer_id}/{stamp}.{_FORMAT[kind][0]}"


class EvidenceStore:
    """Thin async wrapper around a boto3 S3 client (calls run in a worker thread)."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.s3_bucket
        self._ttl = settings.s3_presign_ttl_seconds
        client_cert = (
            (settings.s3_client_cert, settings.s3_client_key)
            if settings.s3_client_cert and settings.s3_client_key
            else None
        )
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            verify=settings.s3_ca_bundle or True,
            config=Config(
                signature_version="s3v4", s3={"addressing_style": "path"}, client_cert=client_cert
            ),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket(self) -> None:
        def create() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError:
                self._client.create_bucket(Bucket=self._bucket)

        await asyncio.to_thread(create)

    async def _put(self, key: str, body: bytes, content_type: str, encoding: str | None) -> None:
        extra: dict[str, str] = {"ContentType": content_type}
        if encoding:
            extra["ContentEncoding"] = encoding
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=body, **extra
        )

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            body: bytes = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
            return body

        return await asyncio.to_thread(read)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def store(
        self,
        *,
        tenant_id: uuid.UUID,
        source_id: uuid.UUID,
        tracked_offer_id: uuid.UUID,
        observed_at: datetime,
        evidence: Evidence,
    ) -> list[StoredObject]:
        payloads: list[tuple[EvidenceKind, bytes]] = []
        if evidence.html is not None:
            payloads.append((EvidenceKind.HTML, gzip.compress(evidence.html, mtime=0)))
        if evidence.extracted is not None:
            payloads.append(
                (
                    EvidenceKind.EXTRACTED,
                    json.dumps(evidence.extracted, ensure_ascii=False, default=str).encode(),
                )
            )
        if evidence.screenshot_png is not None:
            payloads.append((EvidenceKind.SCREENSHOT, evidence.screenshot_png))
        stored: list[StoredObject] = []
        for kind, body in payloads:
            _, content_type, encoding = _FORMAT[kind]
            key = object_key(tenant_id, source_id, tracked_offer_id, observed_at, kind)
            await self._put(key, body, content_type, encoding)
            stored.append(
                StoredObject(kind, key, content_type, len(body), hashlib.sha256(body).hexdigest())
            )
        return stored

    def presign(self, key: str, content_type: str) -> str:
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key, "ResponseContentType": content_type},
            ExpiresIn=self._ttl,
        )
        return url


async def register(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source_id: uuid.UUID,
    tracked_offer_id: uuid.UUID,
    observed_at: datetime,
    objects: list[StoredObject],
) -> list[EvidenceObjectRow]:
    rows = [
        EvidenceObjectRow(
            id=new_id(),
            tenant_id=tenant_id,
            source_id=source_id,
            tracked_offer_id=tracked_offer_id,
            kind=o.kind.value,
            object_key=o.key,
            content_type=o.content_type,
            size_bytes=o.size_bytes,
            sha256=o.sha256,
            observed_at=observed_at,
        )
        for o in objects
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def presigned_url(
    session: AsyncSession, store: EvidenceStore, evidence_id: uuid.UUID
) -> tuple[EvidenceObjectRow, str]:
    """RLS-checked lookup, then a short-lived URL. Unknown or foreign ids are 404."""
    row = await session.get(EvidenceObjectRow, evidence_id)
    if row is None:
        raise NotFound("Evidence not found", message_fa="مستند یافت نشد.")
    if row.expired_at is not None:
        raise NotFound(
            "Evidence snapshot expired",
            code="evidence_expired",
            message_fa="مهلت نگهداری این مستند به پایان رسیده و حذف شده است.",
        )
    return row, store.presign(row.object_key, row.content_type)
