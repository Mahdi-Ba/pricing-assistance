import pytest
from redis.asyncio import Redis

from pricing_assistant.audit.api import list_events
from pricing_assistant.core.crypto import SecretBox
from pricing_assistant.core.db import Database
from pricing_assistant.core.settings import get_settings
from pricing_assistant.sources.runtime import active_rule
from tests.support.api import api_client, auth
from tests.support.fixtures import fixture_json, fixture_text
from tests.support.seed import seed_source

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN = auth(TENANT_A, "admin")
GOOD_RULE = fixture_json("generic/marketplace_rule.json")
BAD_RULE = {**GOOD_RULE, "price": {"selector": ".no-such-price"}, "stock": None}
BOX = SecretBox.from_setting(get_settings().secret_encryption_keys)


async def test_proposed_rule_waits_for_approval_then_replaces_active(
    db: Database, redis_client: Redis
) -> None:
    source_id = await seed_source(db, TENANT_A)
    sample = fixture_text("generic/marketplace_sellers.html").encode()
    async with api_client(db) as client:
        added = await client.post(
            f"/sources/{source_id}/samples",
            headers=ADMIN,
            data={"url": "https://www.lioncomputer.com/p/990"},
            files={"file": ("p.html", sample, "text/html")},
        )
        assert added.status_code == 201
        first = (
            await client.post(
                f"/sources/{source_id}/extraction-rules", headers=ADMIN, json={"config": GOOD_RULE}
            )
        ).json()
        assert first["state"] == "proposed"
        assert first["validation"]["passed"] is True
        assert first["validation"]["results"][0]["offers"] == 4

        async with db.tenant_session(TENANT_A) as session:
            assert await active_rule(session, source_id) is None  # not live yet

        approved = await client.post(
            f"/extraction-rules/{first['id']}/review",
            headers=ADMIN,
            json={"decision": "approve", "reason": "matches all sample sellers"},
        )
        assert approved.json()["state"] == "active"

        second = (
            await client.post(
                f"/sources/{source_id}/extraction-rules", headers=ADMIN, json={"config": GOOD_RULE}
            )
        ).json()
        async with db.tenant_session(TENANT_A) as session:
            live = await active_rule(session, source_id)
        assert live is not None
        assert str(live.version_id) == first["id"]  # still the approved one

        await client.post(
            f"/extraction-rules/{second['id']}/review",
            headers=ADMIN,
            json={"decision": "approve", "reason": "refresh"},
        )
        versions = (
            await client.get(f"/sources/{source_id}/extraction-rules", headers=ADMIN)
        ).json()

    assert [(v["version"], v["state"]) for v in versions] == [(2, "active"), (1, "retired")]
    async with db.tenant_session(TENANT_A) as session:
        actions = [e.action for e in await list_events(session)]
    assert actions.count("source.extraction_rule.approved") == 2


async def test_rule_failing_on_samples_cannot_be_approved(db: Database) -> None:
    source_id = await seed_source(db, TENANT_A)
    async with api_client(db) as client:
        await client.post(
            f"/sources/{source_id}/samples",
            headers=ADMIN,
            data={"url": "https://www.lioncomputer.com/p/990"},
            files={
                "file": (
                    "p.html",
                    fixture_text("generic/marketplace_sellers.html").encode(),
                    "text/html",
                )
            },
        )
        proposed = (
            await client.post(
                f"/sources/{source_id}/extraction-rules", headers=ADMIN, json={"config": BAD_RULE}
            )
        ).json()
        review = await client.post(
            f"/extraction-rules/{proposed['id']}/review",
            headers=ADMIN,
            json={"decision": "approve", "reason": "try"},
        )
        invalid = await client.post(
            f"/sources/{source_id}/extraction-rules",
            headers=ADMIN,
            json={"config": {"price": {"selector": ""}}},
        )
    assert proposed["validation"]["passed"] is False
    assert "error" in proposed["validation"]["results"][0]
    assert review.status_code == 409
    assert review.json()["type"].endswith("rule_validation_failed")
    assert invalid.status_code == 422


async def test_sample_must_be_on_source_domain(db: Database) -> None:
    source_id = await seed_source(db, TENANT_A)
    async with api_client(db) as client:
        response = await client.post(
            f"/sources/{source_id}/samples",
            headers=ADMIN,
            data={"url": "https://elsewhere.test/p"},
            files={"file": ("p.html", b"<html></html>", "text/html")},
        )
    assert response.status_code == 422
