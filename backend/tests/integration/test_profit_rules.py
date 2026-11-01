import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from pricing_assistant.audit.api import AuditActor
from pricing_assistant.catalog.importing import run_import
from pricing_assistant.catalog.models import VariantRow
from pricing_assistant.catalog.rules import (
    SUGGESTED_DEFAULTS,
    RuleFields,
    RuleScope,
    create_version,
    history,
    resolve_for_variant,
)
from pricing_assistant.catalog.upload import FileFormat, Upload
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import ValidationFailed
from tests.support.catalog_files import csv_bytes, row

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN = AuditActor(subject="admin-1", username="pilot-admin")
DEFAULT = SUGGESTED_DEFAULTS.overlay(RuleFields(vat_rate_bp=1_000))


async def _seed(db: Database) -> dict[str, uuid.UUID]:
    async with db.tenant_session(TENANT_A) as session:
        await run_import(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            upload=Upload(
                file_name="c.csv",
                file_format=FileFormat.CSV,
                data=csv_bytes([row("SSD-1"), row("GPU-1", category="gpu")]),
            ),
            default_currency=None,
            max_rows=10,
        )
        variants = (await session.scalars(select(VariantRow))).all()
    return {v.sku: v.id for v in variants}


async def _create(
    db: Database, scope: RuleScope, key: str | None, values: RuleFields, reason: str = "test"
) -> uuid.UUID:
    async with db.tenant_session(TENANT_A) as session:
        version = await create_version(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            scope=scope,
            scope_key=key,
            values=values,
            reason=reason,
        )
    return version.id


async def test_category_rule_overrides_default(db: Database) -> None:
    variants = await _seed(db)
    await _create(db, RuleScope.DEFAULT, None, DEFAULT)
    await _create(db, RuleScope.CATEGORY, "ssd", RuleFields(min_margin_bp=1_200))

    async with db.tenant_session(TENANT_A) as session:
        ssd = await resolve_for_variant(session, variants["SSD-1"])
        gpu = await resolve_for_variant(session, variants["GPU-1"])
    assert ssd is not None
    assert gpu is not None
    assert (ssd.min_margin_bp, gpu.min_margin_bp) == (1_200, 1_000)


async def test_rule_edit_creates_new_version_and_keeps_old(db: Database) -> None:
    variants = await _seed(db)
    await _create(db, RuleScope.DEFAULT, None, DEFAULT)
    first = await _create(db, RuleScope.CATEGORY, "gpu", RuleFields(min_margin_bp=800))
    second = await _create(db, RuleScope.CATEGORY, "gpu", RuleFields(min_margin_bp=900), "raise")

    async with db.tenant_session(TENANT_A) as session:
        versions = await history(session, RuleScope.CATEGORY, "gpu")
        resolved = await resolve_for_variant(session, variants["GPU-1"])
    assert [(v.id, v.version, v.min_margin_bp) for v in versions] == [
        (second, 2, 900),
        (first, 1, 800),
    ]
    assert resolved is not None
    assert resolved.min_margin_bp == 900
    assert second in resolved.version_ids
    assert first not in resolved.version_ids


async def test_default_rule_requires_explicit_vat(db: Database) -> None:
    with pytest.raises(ValidationFailed) as exc:
        await _create(db, RuleScope.DEFAULT, None, SUGGESTED_DEFAULTS)
    assert "vat_rate_bp" in exc.value.detail
    assert "مالیات" in exc.value.message_fa


async def test_margin_plus_fee_must_stay_below_100_percent(db: Database) -> None:
    await _seed(db)
    await _create(db, RuleScope.DEFAULT, None, DEFAULT.overlay(RuleFields(fee_rate_bp=2_000)))
    with pytest.raises(ValidationFailed, match="below 10000"):
        await _create(db, RuleScope.CATEGORY, "ssd", RuleFields(min_margin_bp=8_000))


async def test_overrides_need_a_default_rule(db: Database) -> None:
    with pytest.raises(ValidationFailed, match="default rule first"):
        await _create(db, RuleScope.CATEGORY, "ssd", RuleFields(min_margin_bp=1_200))


async def test_rule_versions_are_append_only(db: Database) -> None:
    await _create(db, RuleScope.DEFAULT, None, DEFAULT)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text("UPDATE profit_rule_version SET min_margin_bp = 1"))
