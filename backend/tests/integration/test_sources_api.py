import pytest
from sqlalchemy import select, text

from pricing_assistant.audit.api import list_events
from pricing_assistant.core.crypto import SecretBox
from pricing_assistant.core.db import Database
from pricing_assistant.core.settings import get_settings
from pricing_assistant.sources.config import decrypted_secrets
from pricing_assistant.sources.models import ConnectorSecretRow
from tests.support.api import api_client, auth
from tests.support.seed import seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN = auth(TENANT_A, "admin")
EXPERT = auth(TENANT_A, "expert", username="pilot-expert")
SECRET = "torob-shop-api-token-THAT-MUST-NOT-LEAK"
SOURCE = {
    "name": "Torob Shop API",
    "base_domain": "api.torob.com",
    "connector_key": "torob_shop_api",
    "method": "api",
    "currency_unit": "TOMAN",
    "quota_per_minute": 30,
}
CLEARANCE = {
    "approver_name": "Store owner + Tunoo legal",
    "approved_on": "2026-10-21",
    "scope": "own shop listing via official Shop API",
    "reference": "TOROB-CONTRACT-17",
    "permitted_requests_per_minute": 60,
}


async def test_connector_secret_is_write_only(db: Database) -> None:
    async with api_client(db) as client:
        source = (await client.post("/sources", headers=ADMIN, json=SOURCE)).json()
        put = await client.put(
            f"/sources/{source['id']}/secrets/api_token", headers=ADMIN, json={"value": SECRET}
        )
        detail = await client.get(f"/sources/{source['id']}", headers=ADMIN)
        listing = await client.get("/sources", headers=EXPERT)
        rejected = await client.put(
            f"/sources/{source['id']}/connector-config",
            headers=ADMIN,
            json={"config": {"api_token": SECRET}},
        )
    assert put.status_code == 204
    assert put.content == b""
    assert detail.json()["secrets"] == {"api_token": "set"}
    for response in (put, detail, listing, rejected):
        assert SECRET not in response.text
    assert rejected.status_code == 422

    async with db.tenant_session(TENANT_A) as session:
        stored = await session.scalar(select(ConnectorSecretRow))
        assert stored is not None
        assert SECRET.encode() not in stored.ciphertext
        audit = await list_events(session)
        plain = await decrypted_secrets(
            session,
            SecretBox.from_setting(get_settings().secret_encryption_keys),
            TENANT_A,
            stored.source_id,
        )
        raw_audit = (
            await session.execute(text("SELECT before::text, after::text FROM audit_event"))
        ).all()
    assert plain == {"api_token": SECRET}
    assert "source.secret.set" in [e.action for e in audit]
    assert all(SECRET not in (b or "") + (a or "") for b, a in raw_audit)


async def test_source_lifecycle_and_offer_registration_via_api(db: Database) -> None:
    variant_id = await seed_variant(db, TENANT_A)
    async with api_client(db) as client:
        source = (
            await client.post(
                "/sources",
                headers=ADMIN,
                json={
                    **SOURCE,
                    "name": "Lion",
                    "base_domain": "lioncomputer.com",
                    "method": "html",
                    "connector_key": "generic_html",
                },
            )
        ).json()
        sid = source["id"]
        offer_body = {
            "source_id": sid,
            "variant_id": str(variant_id),
            "url": "https://www.lioncomputer.com/p/990",
        }
        too_early = await client.post("/tracked-offers", headers=EXPERT, json=offer_body)
        no_clearance = await client.post(
            f"/sources/{sid}/status",
            headers=ADMIN,
            json={"status": "under_evaluation", "reason": "phase A"},
        )
        granted = await client.post(f"/sources/{sid}/clearances", headers=ADMIN, json=CLEARANCE)
        evaluating = await client.post(
            f"/sources/{sid}/status",
            headers=ADMIN,
            json={"status": "under_evaluation", "reason": "phase A"},
        )
        registered = await client.post("/tracked-offers", headers=EXPERT, json=offer_body)
        off_domain = await client.post(
            "/tracked-offers", headers=EXPERT, json={**offer_body, "url": "https://evil.test/p"}
        )
        own_by_expert = await client.post(
            "/tracked-offers",
            headers=EXPERT,
            json={**offer_body, "url": "https://lioncomputer.com/x", "is_own_store": True},
        )
        listed = await client.get(f"/variants/{variant_id}/tracked-offers", headers=EXPERT)
        expert_status = await client.post(
            f"/sources/{sid}/status", headers=EXPERT, json={"status": "approved", "reason": "x"}
        )

    assert too_early.status_code == 409
    assert no_clearance.status_code == 409
    assert no_clearance.json()["type"].endswith("clearance_missing")
    assert granted.status_code == 201
    assert evaluating.json()["status"] == "under_evaluation"
    assert registered.status_code == 201
    assert registered.json()["status"] == "active"
    assert registered.json()["next_due_at"] is not None
    assert off_domain.status_code == 422
    assert own_by_expert.status_code == 403
    assert [o["id"] for o in listed.json()] == [registered.json()["id"]]
    assert expert_status.status_code == 403
