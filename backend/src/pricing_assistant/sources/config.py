"""Connector configuration and write-only connector secrets (task 4.9).

Secret values are encrypted at rest and only ever decrypted inside the collection workers.
No API response, log line or evidence snapshot contains them; admins see set/unset only.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.core.crypto import SecretBox
from pricing_assistant.core.errors import NotFound, ValidationFailed
from pricing_assistant.sources.models import ConnectorConfigRow, ConnectorSecretRow
from pricing_assistant.sources.registry import get_source

_SECRET_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
_FORBIDDEN_CONFIG_KEYS = re.compile(r"(secret|token|password|api_?key|cookie)", re.IGNORECASE)


def _context(tenant_id: uuid.UUID, source_id: uuid.UUID, name: str) -> str:
    return f"{tenant_id}:{source_id}:{name}"


async def get_config(session: AsyncSession, source_id: uuid.UUID) -> dict[str, Any]:
    row = await session.get(ConnectorConfigRow, source_id)
    return dict(row.config) if row else {}


async def put_config(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    config: dict[str, Any],
) -> dict[str, Any]:
    await get_source(session, source_id)
    leaked = [key for key in config if _FORBIDDEN_CONFIG_KEYS.search(key)]
    if leaked:
        raise ValidationFailed(
            f"Store {', '.join(leaked)} as connector secrets, not in the configuration",
            code="secret_in_config",
            message_fa="مقادیر محرمانه را در بخش رمزها ذخیره کنید، نه در تنظیمات.",
        )
    row = await session.get(ConnectorConfigRow, source_id, with_for_update=True)
    before = dict(row.config) if row else None
    if row is None:
        row = ConnectorConfigRow(
            source_id=source_id, tenant_id=tenant_id, config=config, updated_by=actor.username
        )
        session.add(row)
    else:
        row.config = config
        row.updated_by = actor.username
        row.updated_at = datetime.now(UTC)
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.connector_config.changed",
        target_type="source",
        target_id=source_id,
        before=before,
        after=config,
    )
    return config


async def secret_names(session: AsyncSession, source_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(ConnectorSecretRow.name).where(ConnectorSecretRow.source_id == source_id)
    )
    return sorted(rows.all())


async def set_secret(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    box: SecretBox,
    source_id: uuid.UUID,
    name: str,
    value: str,
) -> None:
    if not _SECRET_NAME.fullmatch(name):
        raise ValidationFailed("Secret names are lower-case identifiers")
    if not value:
        raise ValidationFailed("Secret value must not be empty")
    await get_source(session, source_id)
    ciphertext, version = box.encrypt(value, context=_context(tenant_id, source_id, name))
    row = await session.get(ConnectorSecretRow, (source_id, name), with_for_update=True)
    if row is None:
        session.add(
            ConnectorSecretRow(
                source_id=source_id,
                name=name,
                tenant_id=tenant_id,
                ciphertext=ciphertext,
                key_version=version,
                updated_by=actor.username,
            )
        )
    else:
        row.ciphertext = ciphertext
        row.key_version = version
        row.updated_by = actor.username
        row.updated_at = datetime.now(UTC)
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.secret.set",
        target_type="source",
        target_id=source_id,
        after={"name": name, "set": True},
    )


async def delete_secret(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    name: str,
) -> None:
    result = await session.execute(
        delete(ConnectorSecretRow)
        .where(ConnectorSecretRow.source_id == source_id, ConnectorSecretRow.name == name)
        .returning(ConnectorSecretRow.name)
    )
    if result.first() is None:
        raise NotFound("Secret not set", message_fa="این رمز تنظیم نشده است.")
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.secret.deleted",
        target_type="source",
        target_id=source_id,
        after={"name": name, "set": False},
    )


async def decrypted_secrets(
    session: AsyncSession, box: SecretBox, tenant_id: uuid.UUID, source_id: uuid.UUID
) -> dict[str, str]:
    """For collection workers only: the plaintext secrets of one source."""
    rows = await session.scalars(
        select(ConnectorSecretRow).where(ConnectorSecretRow.source_id == source_id)
    )
    return {
        row.name: box.decrypt(
            row.ciphertext,
            version=row.key_version,
            context=_context(tenant_id, source_id, row.name),
        )
        for row in rows.all()
    }
