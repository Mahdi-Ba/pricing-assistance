"""Editing and deleting sources: allowed changes, guards and audit trail."""

import pytest

from pricing_assistant.audit.api import list_events
from pricing_assistant.core.db import Database
from tests.support.api import api_client, auth
from tests.support.seed import seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN = auth(TENANT_A, "admin")
EXPERT = auth(TENANT_A, "expert", username="pilot-expert")
SOURCE = {
    "name": "Typo Shop",
    "base_domain": "www.typo.example",
    "connector_key": "generic_html",
    "method": "html",
    "currency_unit": "TOMAN",
    "quota_per_minute": 10,
}
CLEARANCE = {
    "approver_name": "Store owner",
    "approved_on": "2026-10-21",
    "scope": "public product pages",
    "reference": "LEGAL-7",
    "permitted_requests_per_minute": 20,
}


async def test_candidate_is_fully_editable_and_audited(db: Database) -> None:
    async with api_client(db) as client:
        source = (await client.post("/sources", headers=ADMIN, json=SOURCE)).json()
        edited = await client.patch(
            f"/sources/{source['id']}",
            headers=ADMIN,
            json={
                "name": "Fixed Shop",
                "base_domain": "www.fixed.example",
                "connector_key": "generic_html",
                "method": "rendered_page",
                "currency_unit": "RIAL",
                "settings": {"quota_per_minute": 12, "interval_a_seconds": 600},
            },
        )
        unchanged = await client.patch(f"/sources/{source['id']}", headers=ADMIN, json={})
        by_expert = await client.patch(
            f"/sources/{source['id']}", headers=EXPERT, json={"name": "Nope"}
        )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["name"], body["base_domain"], body["method"], body["currency_unit"]) == (
        "Fixed Shop",
        "www.fixed.example",
        "rendered_page",
        "RIAL",
    )
    assert (body["quota_per_minute"], body["interval_a_seconds"]) == (12, 600)
    assert unchanged.status_code == 200
    assert by_expert.status_code == 403

    async with db.tenant_session(TENANT_A) as session:
        updates = [e for e in await list_events(session) if e.action == "source.updated"]
    assert len(updates) == 1  # the empty edit records nothing
    before, after = updates[0].before or {}, updates[0].after or {}
    assert before["name"] == "Typo Shop"
    assert after["method"] == "rendered_page"
    assert "connector_key" not in after  # unchanged fields are not recorded


async def test_collecting_source_keeps_its_collection_settings(db: Database) -> None:
    variant_id = await seed_variant(db, TENANT_A)
    async with api_client(db) as client:
        source = (await client.post("/sources", headers=ADMIN, json=SOURCE)).json()
        sid = source["id"]
        await client.post(f"/sources/{sid}/clearances", headers=ADMIN, json=CLEARANCE)
        await client.post(
            f"/sources/{sid}/status",
            headers=ADMIN,
            json={"status": "under_evaluation", "reason": "qualification"},
        )
        method = await client.patch(f"/sources/{sid}", headers=ADMIN, json={"method": "api"})
        renamed = await client.patch(f"/sources/{sid}", headers=ADMIN, json={"name": "Renamed"})
        quota = await client.patch(
            f"/sources/{sid}", headers=ADMIN, json={"settings": {"quota_per_minute": 50}}
        )
        await client.post(
            "/tracked-offers",
            headers=EXPERT,
            json={
                "source_id": sid,
                "variant_id": str(variant_id),
                "url": "https://www.typo.example/p/1",
            },
        )
        await client.post(
            f"/sources/{sid}/status", headers=ADMIN, json={"status": "suspended", "reason": "pause"}
        )
        currency = await client.patch(
            f"/sources/{sid}", headers=ADMIN, json={"currency_unit": "RIAL"}
        )
        domain = await client.patch(
            f"/sources/{sid}", headers=ADMIN, json={"base_domain": "www.other.example"}
        )
    assert method.status_code == 409
    assert method.json()["type"].endswith("source_collecting")
    assert renamed.status_code == 200
    assert quota.status_code == 422  # above the clearance's permitted rate
    assert currency.status_code == 200  # suspended: collection settings may change
    assert domain.status_code == 409
    assert domain.json()["type"].endswith("source_has_offers")


async def test_only_an_unused_candidate_can_be_deleted(db: Database) -> None:
    async with api_client(db) as client:
        unused = (await client.post("/sources", headers=ADMIN, json=SOURCE)).json()
        cleared = (
            await client.post("/sources", headers=ADMIN, json={**SOURCE, "name": "Cleared"})
        ).json()
        await client.post(f"/sources/{cleared['id']}/clearances", headers=ADMIN, json=CLEARANCE)
        rejected = (
            await client.post("/sources", headers=ADMIN, json={**SOURCE, "name": "Rejected"})
        ).json()
        await client.post(
            f"/sources/{rejected['id']}/status",
            headers=ADMIN,
            json={"status": "rejected", "reason": "not needed"},
        )

        no_reason = await client.request(
            "DELETE", f"/sources/{unused['id']}", headers=ADMIN, json={"reason": " "}
        )
        by_expert = await client.request(
            "DELETE", f"/sources/{unused['id']}", headers=EXPERT, json={"reason": "typo"}
        )
        deleted = await client.request(
            "DELETE", f"/sources/{unused['id']}", headers=ADMIN, json={"reason": "typo"}
        )
        in_use = await client.request(
            "DELETE", f"/sources/{cleared['id']}", headers=ADMIN, json={"reason": "typo"}
        )
        not_candidate = await client.request(
            "DELETE", f"/sources/{rejected['id']}", headers=ADMIN, json={"reason": "typo"}
        )
        names = [s["name"] for s in (await client.get("/sources", headers=ADMIN)).json()]
    assert no_reason.status_code == 422
    assert by_expert.status_code == 403
    assert deleted.status_code == 204
    assert in_use.status_code == 409
    assert in_use.json()["type"].endswith("source_in_use")
    assert not_candidate.status_code == 409
    assert not_candidate.json()["type"].endswith("source_not_deletable")
    assert sorted(names) == ["Cleared", "Rejected"]

    async with db.tenant_session(TENANT_A) as session:
        events = await list_events(session)
    deletions = [e for e in events if e.action == "source.deleted"]
    assert len(deletions) == 1
    assert (deletions[0].before or {})["name"] == "Typo Shop"
    assert deletions[0].reason == "typo"
