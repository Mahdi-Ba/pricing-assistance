"""The example in docs/catalog-import.md must import successfully."""

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from pricing_assistant.audit.api import AuditActor
from pricing_assistant.catalog.importing import run_import
from pricing_assistant.catalog.models import VariantRow
from pricing_assistant.catalog.upload import FileFormat, Upload
from pricing_assistant.core.db import Database

from .conftest import BACKEND_DIR, TENANT_A

pytestmark = pytest.mark.integration

DOC = BACKEND_DIR.parent / "docs" / "catalog-import.md"
EXAMPLE = re.compile(
    r"<!-- catalog-import-example:start -->\s*```csv\n(.*?)```\s*"
    r"<!-- catalog-import-example:end -->",
    re.S,
)


def example_csv(path: Path = DOC) -> bytes:
    match = EXAMPLE.search(path.read_text(encoding="utf-8"))
    assert match, "example block missing from docs/catalog-import.md"
    return match.group(1).encode("utf-8")


async def test_documented_example_imports(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        result = await run_import(
            session,
            tenant_id=TENANT_A,
            actor=AuditActor(subject="docs", username="docs"),
            upload=Upload(file_name="example.csv", file_format=FileFormat.CSV, data=example_csv()),
            default_currency=None,
            max_rows=100,
        )
        variants = {v.sku: v for v in (await session.scalars(select(VariantRow))).all()}

    assert result.status == "succeeded", result.errors
    assert result.rows_created == 3
    assert variants["SSD-990P-2T"].current_price_rial == 164_000_000
    assert variants["GPU-4060-8G"].cost_status == "cost_missing"
    assert variants["SSD-990P-1T"].importance_tier == "A"
