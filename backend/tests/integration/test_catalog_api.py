import uuid

import pytest
from sqlalchemy import select

from pricing_assistant.audit.api import list_events
from pricing_assistant.catalog.models import VariantRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import OutboxEventRow
from pricing_assistant.core.settings import get_settings
from tests.support.api import api_client, auth
from tests.support.catalog_files import csv_bytes, row

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN = auth(TENANT_A, "admin")
EXPERT = auth(TENANT_A, "expert", username="pilot-expert")
DEFAULT_RULE = {
    "min_margin_bp": 1000,
    "fee_rate_bp": 0,
    "vat_rate_bp": 1000,
    "undercut_step_rial": 500_000,
    "hold_tolerance_bp": 100,
    "rounding_step_rial": 100_000,
    "max_data_age_a_seconds": 7200,
    "max_data_age_b_seconds": 14400,
    "max_data_age_c_seconds": 86400,
    "outlier_threshold_bp": 1500,
    "min_qualifying_offers": 1,
    "reason": "initial pilot rule",
}


async def _events(db: Database) -> list[str]:
    async with db.tenant_session(TENANT_A) as session:
        rows = await session.scalars(select(OutboxEventRow).order_by(OutboxEventRow.occurred_at))
        return [r.type for r in rows.all()]


async def _audit_actions(db: Database) -> list[str]:
    async with db.tenant_session(TENANT_A) as session:
        return [e.action for e in await list_events(session)]


def _file(data: bytes, name: str = "catalog.csv") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, data, "text/csv")}


async def test_import_upload_report_and_events(db: Database) -> None:
    async with api_client(db) as client:
        created = await client.post(
            "/catalog/imports",
            headers=ADMIN,
            files=_file(csv_bytes([row("SSD-1", currency=""), row("SSD-2", currency="")])),
            data={"default_currency": "TOMAN"},
        )
        assert created.status_code == 201, created.text
        report = created.json()
        fetched = await client.get(f"/catalog/imports/{report['id']}", headers=ADMIN)
        listed = await client.get("/catalog/imports", headers=ADMIN)

    assert report["status"] == "succeeded"
    assert report["rows_created"] == 2
    assert report["default_currency"] == "TOMAN"
    assert fetched.json() == report
    assert [r["id"] for r in listed.json()] == [report["id"]]
    assert await _events(db) == ["catalog.cost.changed", "catalog.variants.changed"]
    assert "catalog.import.completed" in await _audit_actions(db)


async def test_import_is_admin_only(db: Database) -> None:
    async with api_client(db) as client:
        response = await client.post(
            "/catalog/imports", headers=EXPERT, files=_file(csv_bytes([row("SSD-1")]))
        )
    assert response.status_code == 403
    assert await _audit_actions(db) == ["authorization.denied"]


async def test_oversized_upload_rejected_before_parsing(db: Database) -> None:
    settings = get_settings().model_copy(update={"catalog_max_upload_bytes": 2048})
    async with api_client(db, settings) as client:
        response = await client.post(
            "/catalog/imports", headers=ADMIN, files=_file(b"sku\n" + b"A" * 10_000)
        )
        listed = await client.get("/catalog/imports", headers=ADMIN)
    assert response.status_code == 413
    assert response.json()["message_fa"]
    assert listed.json() == []


async def test_unsupported_file_type_is_rejected(db: Database) -> None:
    async with api_client(db) as client:
        response = await client.post(
            "/catalog/imports", headers=ADMIN, files=_file(b"%PDF-1.7", name="catalog.pdf")
        )
    assert response.status_code == 415


async def test_import_with_idempotency_key_replays(db: Database) -> None:
    files = _file(csv_bytes([row("SSD-1")]))
    headers = {**ADMIN, "Idempotency-Key": "import-0001"}
    async with api_client(db) as client:
        first = await client.post("/catalog/imports", headers=headers, files=files)
        second = await client.post("/catalog/imports", headers=headers, files=files)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers["Idempotency-Replayed"] == "true"


async def test_template_lists_required_columns(db: Database) -> None:
    async with api_client(db) as client:
        response = await client.get("/catalog/import-template", headers=ADMIN)
    assert response.status_code == 200
    header = response.content.decode("utf-8-sig").splitlines()[0].split(",")
    assert header[:7] == [
        "sku",
        "product_name",
        "category",
        "brand",
        "model",
        "current_price",
        "purchase_cost",
    ]


async def test_cost_components_and_cost_review(db: Database) -> None:
    async with api_client(db) as client:
        await client.post(
            "/catalog/imports",
            headers=ADMIN,
            files=_file(csv_bytes([row("SSD-1", purchase_cost="1,000,000", currency="RIAL")])),
        )
        await client.post(
            "/catalog/imports",
            headers=ADMIN,
            files=_file(csv_bytes([row("SSD-1", purchase_cost="9,000,000", currency="RIAL")])),
        )
        component = await client.post(
            "/catalog/cost-components",
            headers=ADMIN,
            json={"name": "حمل", "amount_rial": 200_000, "category": "ssd"},
        )
        assert component.status_code == 201
        deactivated = await client.post(
            f"/catalog/cost-components/{component.json()['id']}/deactivate",
            headers=ADMIN,
            json={"reason": "included in supplier price"},
        )
        assert deactivated.json()["active"] is False
        imports = (await client.get("/catalog/imports", headers=ADMIN)).json()
        assert len(imports) == 2
        async with db.tenant_session(TENANT_A) as session:
            variant = await session.scalar(select(VariantRow))
        assert variant is not None
        history = (await client.get(f"/catalog/variants/{variant.id}/costs", headers=ADMIN)).json()
        assert [h["state"] for h in history] == ["held", "applied"]
        reviewed = await client.post(
            f"/catalog/costs/{history[0]['id']}/review",
            headers=ADMIN,
            json={"decision": "confirm", "reason": "supplier invoice checked"},
        )
    assert reviewed.status_code == 200
    assert reviewed.json()["state"] == "confirmed"
    actions = await _audit_actions(db)
    assert {
        "catalog.cost_component.created",
        "catalog.cost_component.deactivated",
        "catalog.cost.confirmed",
    } <= set(actions)
    assert (await _events(db)).count("catalog.cost.changed") >= 4


async def test_rules_api(db: Database) -> None:
    async with api_client(db) as client:
        suggested = await client.get("/rules/suggested-defaults", headers=ADMIN)
        assert suggested.json()["vat_rate_bp"] is None
        missing_vat = await client.put(
            "/rules/default", headers=ADMIN, json={**DEFAULT_RULE, "vat_rate_bp": None}
        )
        assert missing_vat.status_code == 422
        assert "مالیات" in missing_vat.json()["message_fa"]
        denied = await client.put("/rules/default", headers=EXPERT, json=DEFAULT_RULE)
        assert denied.status_code == 403

        created = await client.put("/rules/default", headers=ADMIN, json=DEFAULT_RULE)
        assert created.status_code == 201
        category = await client.put(
            "/rules/category/SSD", headers=ADMIN, json={"min_margin_bp": 1200, "reason": "ssd"}
        )
        assert category.json()["scope_key"] == "ssd"
        await client.post("/catalog/imports", headers=ADMIN, files=_file(csv_bytes([row("SSD-1")])))
        async with db.tenant_session(TENANT_A) as session:
            variant = await session.scalar(select(VariantRow))
        assert variant is not None
        resolved = await client.get(f"/rules/resolved/{variant.id}", headers=EXPERT)
        current = await client.get("/rules", headers=EXPERT)
        missing = await client.get(f"/rules/resolved/{uuid.uuid4()}", headers=EXPERT)

    assert resolved.json()["min_margin_bp"] == 1200
    assert resolved.json()["max_data_age_seconds"] == {"A": 7200, "B": 14400, "C": 86400}
    assert len(current.json()) == 2
    assert missing.status_code == 404
    assert (await _events(db)).count("rule.version.created") == 2
    assert (await _audit_actions(db)).count("rule.version.created") == 2


async def test_same_idempotency_key_with_different_file_is_rejected(db: Database) -> None:
    headers = {**ADMIN, "Idempotency-Key": "import-0002"}
    async with api_client(db) as client:
        await client.post("/catalog/imports", headers=headers, files=_file(csv_bytes([row("A")])))
        other = await client.post(
            "/catalog/imports", headers=headers, files=_file(csv_bytes([row("B")]))
        )
    assert other.status_code == 422
    assert other.json()["type"].endswith("idempotency_key_reused")


async def test_variant_list_and_held_costs(db: Database) -> None:
    async with api_client(db) as client:
        first = await client.post(
            "/catalog/imports",
            files=_file(csv_bytes([row("SSD-1", purchase_cost="84,000,000", currency="RIAL")])),
            headers=ADMIN,
        )
        second = await client.post(
            "/catalog/imports",
            files=_file(csv_bytes([row("SSD-1", purchase_cost="84,000,000", currency="TOMAN")])),
            headers=ADMIN,
        )
        variants = (
            await client.get("/catalog/variants", params={"q": "ssd-1"}, headers=EXPERT)
        ).json()
        none = (
            await client.get("/catalog/variants", params={"q": "nothing"}, headers=EXPERT)
        ).json()
        held = await client.get(
            "/catalog/held-costs", params={"import_id": second.json()["id"]}, headers=ADMIN
        )
        expert_held = await client.get("/catalog/held-costs", headers=EXPERT)
        other_import = (
            await client.get(
                "/catalog/held-costs", params={"import_id": first.json()["id"]}, headers=ADMIN
            )
        ).json()
    assert [v["sku"] for v in variants] == ["SSD-1"]
    assert "purchase_cost_rial" not in variants[0]  # no cost data for experts
    assert none == []
    assert held.status_code == 200
    assert [(h["state"], h["purchase_cost_rial"]) for h in held.json()] == [("held", 840_000_000)]
    assert expert_held.status_code == 403
    assert other_import == []
