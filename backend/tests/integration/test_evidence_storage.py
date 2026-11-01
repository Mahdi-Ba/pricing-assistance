import gzip
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest

from pricing_assistant.collection.evidence import (
    EvidenceKind,
    EvidenceObjectRow,
    EvidenceStore,
    object_key,
    presigned_url,
    register,
)
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import NotFound
from pricing_assistant.core.settings import get_settings
from pricing_assistant.sources.api import Evidence
from tests.support.api import api_client, auth
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration

OBSERVED = datetime(2026, 10, 25, 9, 30, 15, 123456, tzinfo=UTC)
HTML = "<html><body><span class='price'>۸٬۶۰۰٬۰۰۰ تومان</span></body></html>".encode()
PNG = b"\x89PNG\r\n\x1a\nfake"


@pytest.fixture
async def store() -> EvidenceStore:
    evidence_store = EvidenceStore(get_settings())
    await evidence_store.ensure_bucket()
    return evidence_store


@dataclass
class Seeded:
    rows: list[EvidenceObjectRow]
    source: uuid.UUID
    offer: uuid.UUID


async def _stored(db: Database, store: EvidenceStore) -> Seeded:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    objects = await store.store(
        tenant_id=TENANT_A,
        source_id=source,
        tracked_offer_id=offer,
        observed_at=OBSERVED,
        evidence=Evidence(html=HTML, extracted={"price_rial": 86_000_000}, screenshot_png=PNG),
    )
    async with db.tenant_session(TENANT_A) as session:
        rows = await register(
            session,
            tenant_id=TENANT_A,
            source_id=source,
            tracked_offer_id=offer,
            observed_at=OBSERVED,
            objects=objects,
        )
    return Seeded(rows=rows, source=source, offer=offer)


async def test_evidence_is_stored_with_key_scheme_and_readable_via_presigned_url(
    db: Database, store: EvidenceStore
) -> None:
    seeded = await _stored(db, store)
    rows = {r.kind: r for r in seeded.rows}
    assert set(rows) == {"html", "extracted", "screenshot"}
    assert rows["html"].object_key == object_key(
        TENANT_A, seeded.source, seeded.offer, OBSERVED, EvidenceKind.HTML
    )
    assert rows["html"].object_key.endswith("/20261025T093015123456Z.html.gz")

    async with db.tenant_session(TENANT_A) as session:
        _, html_url = await presigned_url(session, store, rows["html"].id)
        _, json_url = await presigned_url(session, store, rows["extracted"].id)
    async with httpx.AsyncClient() as client:
        html_response = await client.get(html_url)
        json_response = await client.get(json_url)
    assert html_response.status_code == 200
    body = html_response.content
    assert (gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body) == HTML
    assert json.loads(json_response.content) == {"price_rial": 86_000_000}


async def test_other_tenant_gets_404(db: Database, store: EvidenceStore) -> None:
    seeded = await _stored(db, store)
    evidence_id = seeded.rows[0].id
    async with db.tenant_session(TENANT_B) as session:
        with pytest.raises(NotFound):
            await presigned_url(session, store, evidence_id)
    async with api_client(db) as client:
        own = await client.get(f"/evidence/{evidence_id}", headers=auth(TENANT_A, "expert"))
        foreign = await client.get(f"/evidence/{evidence_id}", headers=auth(TENANT_B, "expert"))
    assert own.status_code == 200
    assert own.json()["url"].startswith(get_settings().s3_endpoint_url or "")
    assert foreign.status_code == 404
    assert "url" not in foreign.json()
