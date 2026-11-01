import uuid

import pytest
from redis.asyncio import Redis

from pricing_assistant.audit.api import list_events
from pricing_assistant.core.db import Database
from pricing_assistant.sources.api import (
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    OfferTarget,
    SourceStatus,
)
from tests.support.api import api_client, auth
from tests.support.collection import collection_runtime
from tests.support.fakes import RecordingConnector, draft
from tests.support.pipeline import drain
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN = auth(TENANT_A, "admin")


class QualificationConnector(RecordingConnector):
    """Source 'Flaky' fails every third fetch with a parse failure; the others always succeed."""

    def __init__(self, flaky: uuid.UUID) -> None:
        super().__init__()
        self.flaky = flaky

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult:
        self.calls.append(target)
        if target.source_id == self.flaky and len(self.calls) % 3 == 0:
            return FetchFailure(FetchErrorClass.PARSE_FAILURE, "layout")
        return draft(target, seller=None, title="SSD سامسونگ 990 PRO 1TB")


async def test_qualification_completed_and_admin_decides(db: Database, redis_client: Redis) -> None:
    variants = [await seed_variant(db, TENANT_A, sku=f"Q-{i:02d}") for i in range(20)]
    names = ("Lion Computer", "Meghdad IT", "Flaky")
    sources = [
        await seed_source(db, TENANT_A, name=name, status=SourceStatus.UNDER_EVALUATION, quota=600)
        for name in names
    ]
    for source in sources:
        for i, variant in enumerate(variants):
            await seed_offer(
                db,
                TENANT_A,
                source_id=source,
                variant_id=variant,
                url=f"https://www.lioncomputer.com/{source}/{i}",
            )
    uncleared = await seed_source(
        db, TENANT_A, name="NoClearance", status=SourceStatus.CANDIDATE, cleared=False
    )

    async with api_client(db) as client:
        refused = await client.post(
            "/qualification-runs",
            headers=ADMIN,
            json={
                "source_ids": [str(sources[0]), str(uncleared)],
                "variant_ids": [str(v) for v in variants],
            },
        )
        started = await client.post(
            "/qualification-runs",
            headers=ADMIN,
            json={
                "source_ids": [str(s) for s in sources],
                "variant_ids": [str(v) for v in variants],
            },
        )
        assert started.status_code == 201, started.text
        run = started.json()
        runtime, _ = await collection_runtime(db, redis_client, QualificationConnector(sources[2]))
        await drain(db, [TENANT_A], runtime, flush_limiter=redis_client)
        report = (await client.get(f"/qualification-runs/{run['id']}", headers=ADMIN)).json()
        approve = await client.post(
            f"/qualification-runs/{run['id']}/sources/{sources[0]}/decision",
            headers=ADMIN,
            json={"decision": "approve", "reason": "100% extraction and match"},
        )
        reject = await client.post(
            f"/qualification-runs/{run['id']}/sources/{sources[2]}/decision",
            headers=ADMIN,
            json={"decision": "reject", "reason": "unstable extraction"},
        )

    assert refused.status_code == 409
    assert "NoClearance" in refused.json()["message_fa"]
    assert run["requested_offers"] == 60
    assert report["status"] == "completed"
    per_source = {s["name"]: s for s in report["report"]["sources"]}
    assert per_source["Lion Computer"]["extraction_success_rate"] == 1.0
    assert per_source["Lion Computer"]["match_rate"] == 1.0
    assert per_source["Lion Computer"]["variants_tracked"] == 20
    assert per_source["Flaky"]["extraction_success_rate"] < 1.0
    assert per_source["Flaky"]["errors"] == {
        "parse_failure": per_source["Flaky"]["fetches"]
        - round(per_source["Flaky"]["extraction_success_rate"] * 20)
    }
    assert per_source["Meghdad IT"]["freshness_median_seconds"] is not None
    assert approve.json()["status"] == "approved"
    assert reject.json()["status"] == "rejected"
    async with db.tenant_session(TENANT_A) as session:
        decisions = await list_events(session, action="source.qualification.decided")
    assert {d.after["decision"] for d in decisions if d.after} == {"approved", "rejected"}
    assert all(d.after and d.after["clearance_reference"] == "LEGAL-42" for d in decisions)
