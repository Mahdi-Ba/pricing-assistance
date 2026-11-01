"""Reporting: match audit, floor safety, evidence completeness, review time, weekly (13.1–13.4)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from pricing_assistant.catalog.models import ProductRow, VariantRow
from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.decisions.models import (
    DecisionOutcomeRow,
    DecisionRow,
    OverrideReviewRow,
)
from pricing_assistant.llm.models import LLMCallRow
from pricing_assistant.matching.models import MatchVersionRow
from pricing_assistant.pricing.models import RecommendationRow
from pricing_assistant.reporting import audit
from pricing_assistant.reporting.models import MatchAuditItemRow
from pricing_assistant.workspace.sessions import ReviewSessionRow
from tests.support.api import api_client, auth
from tests.support.seed import ADMIN, seed_offer, seed_source

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN_AUTH = auth(TENANT_A, "admin", username="pilot-admin")
EXPERT_AUTH = auth(TENANT_A, "expert", username="pilot-expert")
NOW = datetime.now(UTC)
PERIOD = NOW.strftime("%Y-%m")
TODAY = NOW.date()


async def _variants(db: Database, n: int, category: str, tier: str = "B") -> list[uuid.UUID]:
    ids = []
    async with db.tenant_session(TENANT_A) as session:
        product = ProductRow(
            id=new_id(), tenant_id=TENANT_A, category=category, brand="B", name=category
        )
        session.add(product)
        await session.flush()
        for i in range(n):
            variant = VariantRow(
                id=new_id(),
                tenant_id=TENANT_A,
                product_id=product.id,
                sku=f"{category}-{i}-{uuid.uuid4().hex[:6]}",
                model=f"M{i}",
                attributes={},
                importance_tier=tier,
                current_price_rial=90_000_000,
            )
            session.add(variant)
            ids.append(variant.id)
    return ids


async def _rec(
    db: Database,
    variant: uuid.UUID,
    *,
    outcome: str = "decrease",
    qualifying: list[uuid.UUID] | None = None,
    created: datetime = NOW,
) -> uuid.UUID:
    rec_id = new_id()
    actionable = outcome in ("increase", "decrease")
    async with db.tenant_session(TENANT_A) as session:
        session.add(
            RecommendationRow(
                id=rec_id,
                tenant_id=TENANT_A,
                variant_id=variant,
                outcome=outcome,
                reason_code="above_market",
                flags=[],
                suggested_price_rial=85_000_000 if actionable else None,
                our_price_rial=90_000_000,
                floor_rial=84_000_000,
                market_ref_rial=86_000_000,
                qualifying_count=len(qualifying or []),
                qualifying_observation_ids=qualifying or [],
                excluded_outlier_ids=[],
                explanation="x",
                observation_ids=qualifying or [],
                match_version_ids=[],
                outlier_confirmation_ids=[],
                cost_component_ids=[],
                rule_version_ids=[],
                inputs={
                    "evaluated_at": created.isoformat(),
                    "tier": "B",
                    "our_price_rial": 1,
                    "offers": [],
                },
                evaluated_at=created,
                engine_version="1.0.0",
                created_at=created,
            )
        )
    return rec_id


async def _decision(
    db: Database,
    variant: uuid.UUID,
    rec: uuid.UUID,
    *,
    at: datetime = NOW,
    actor: str = "pilot-expert",
    applied: int | None = None,
    override_reason: str | None = None,
) -> uuid.UUID:
    decision_id = new_id()
    async with db.tenant_session(TENANT_A) as session:
        session.add(
            DecisionRow(
                id=decision_id,
                tenant_id=TENANT_A,
                variant_id=variant,
                recommendation_id=rec,
                type="accept_modified" if applied else "reject",
                reason="r",
                applied_price_rial=applied,
                floor_rial=84_000_000,
                below_floor_override=applied is not None and applied < 84_000_000,
                override_reason=override_reason,
                actor_subject=actor,
                actor=actor,
                created_at=at,
            )
        )
    return decision_id


# --- 13.1 match audit -----------------------------------------------------------------------------


async def _confirmed_matches(db: Database, n: int, *, skew: bool) -> None:
    categories = ["ssd", "gpu", "ram", "cpu"]
    variants = {c: (await _variants(db, 1, c))[0] for c in categories}
    sources = [await seed_source(db, TENANT_A, name=f"src{i}") for i in range(3)]
    offers = {
        (c, s): await seed_offer(
            db,
            TENANT_A,
            source_id=s,
            variant_id=variants[c],
            url=f"https://www.lioncomputer.com/{c}/{s}",
        )
        for c in categories
        for s in sources
    }
    async with db.tenant_session(TENANT_A) as session:
        for i in range(n):
            category = "ssd" if skew and i % 10 else categories[(i // 10) % 4]
            source = sources[0] if skew and i % 7 else sources[i % 3]
            offer = offers[(category, source)]
            kind = i % 4  # 0 exact rule, 1 confirmed proposal high, 2 medium, 3 low
            previous = None
            if kind:
                previous = MatchVersionRow(
                    id=new_id(),
                    tenant_id=TENANT_A,
                    tracked_offer_id=offer,
                    seller_key=f"s{i}",
                    variant_id=variants[category],
                    state="proposed",
                    flags=[],
                    confidence_bp={1: 9_500, 2: 8_500, 3: 7_000}[kind],
                    decided_by="rule",
                    actor="system",
                    attributes_hash="h",
                    is_current=False,
                )
                session.add(previous)
                await session.flush()
            session.add(
                MatchVersionRow(
                    id=new_id(),
                    tenant_id=TENANT_A,
                    tracked_offer_id=offer,
                    seller_key=f"s{i}",
                    variant_id=variants[category],
                    state="confirmed",
                    flags=[],
                    confidence_bp=10_000,
                    decided_by="rule" if not kind else "human",
                    actor="system" if not kind else "pilot-expert",
                    attributes_hash="h",
                    previous_version_id=previous.id if previous else None,
                    is_current=True,
                )
            )


async def test_accuracy_computed_on_a_sample_of_200(db: Database) -> None:
    await _confirmed_matches(db, 260, skew=False)
    async with api_client(db) as client:
        assert (
            await client.post("/reports/match-audits", json={"period": PERIOD}, headers=EXPERT_AUTH)
        ).status_code == 403
        drawn = await client.post(
            "/reports/match-audits", json={"period": PERIOD}, headers=ADMIN_AUTH
        )
    assert drawn.status_code == 201, drawn.text
    sample = drawn.json()
    assert (sample["population"], sample["size"]) == (260, 200)
    items = sample["items"]
    async with api_client(db) as client:
        no_note = await client.post(
            f"/reports/match-audit-items/{items[0]['id']}/verdict",
            json={"verdict": "incorrect"},
            headers=ADMIN_AUTH,
        )
        assert no_note.status_code == 422
        for item in items[:3]:
            response = await client.post(
                f"/reports/match-audit-items/{item['id']}/verdict",
                json={"verdict": "incorrect", "note": "ظرفیت متفاوت"},
                headers=ADMIN_AUTH,
            )
            assert response.status_code == 200
        again = await client.post(
            f"/reports/match-audit-items/{items[0]['id']}/verdict",
            json={"verdict": "correct"},
            headers=ADMIN_AUTH,
        )
        assert again.status_code == 409
    async with db.tenant_session(TENANT_A) as session:
        for item in items[3:]:
            await audit.record_verdict(
                session,
                tenant_id=TENANT_A,
                actor=ADMIN,
                item_id=uuid.UUID(item["id"]),
                correct=True,
                note=None,
            )
    async with api_client(db) as client:
        result = (
            await client.get(f"/reports/match-audits/{sample['id']}", headers=EXPERT_AUTH)
        ).json()
        pilot = (
            await client.get(
                "/reports/pilot", params={"from": str(TODAY), "to": str(TODAY)}, headers=EXPERT_AUTH
            )
        ).json()
    assert result["overall"] == {"reviewed": 200, "correct": 197, "accuracy_pct": 98.5}
    assert result["target_pct"] == 98.0
    assert len(result["incorrect"]) == 3
    assert set(result["by_category"]) == {"ssd", "gpu", "ram", "cpu"}
    assert set(result["by_band"]) == {"exact_identifier", "high", "medium", "low"}
    assert sum(v["reviewed"] for v in result["by_source"].values()) == 200
    assert pilot["match_accuracy"]["overall"]["accuracy_pct"] == 98.5
    assert (pilot["match_accuracy"]["size"], pilot["match_accuracy"]["period"]) == (200, PERIOD)


async def test_stratified_sample_covers_every_category_source_and_band(db: Database) -> None:
    await _confirmed_matches(db, 1_000, skew=True)
    async with db.tenant_session(TENANT_A) as session:
        sample = await audit.draw_sample(session, tenant_id=TENANT_A, actor=ADMIN, period=PERIOD)
        items = (
            await session.scalars(
                select(MatchAuditItemRow).where(MatchAuditItemRow.sample_id == sample.id)
            )
        ).all()
    assert (sample.population, sample.size, len(items)) == (1_000, 200, 200)
    assert {i.category for i in items} == {"ssd", "gpu", "ram", "cpu"}
    assert len({i.source_id for i in items}) == 3
    assert {i.confidence_band for i in items} == {"exact_identifier", "high", "medium", "low"}


# --- 13.2 floor safety and evidence completeness ---------------------------------------------------


async def _valid_observation(
    db: Database, variant: uuid.UUID, *, validity: str = "valid"
) -> uuid.UUID:
    source = await seed_source(db, TENANT_A, name=f"o-{uuid.uuid4().hex[:6]}")
    offer = await seed_offer(
        db,
        TENANT_A,
        source_id=source,
        variant_id=variant,
        url=f"https://www.lioncomputer.com/{uuid.uuid4().hex}",
    )
    observation_id = new_id()
    async with db.tenant_session(TENANT_A) as session:
        attempt = FetchAttemptRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=source,
            window_start=NOW,
            attempt=1,
            trigger="scheduled",
            outcome="success",
            offers_count=1,
            final=True,
            correlation_id="c",
        )
        session.add(attempt)
        await session.flush()
        session.add(
            ObservationRow(
                id=observation_id,
                tenant_id=TENANT_A,
                tracked_offer_id=offer,
                source_id=source,
                variant_id=variant,
                fetch_attempt_id=attempt.id,
                observed_at=NOW,
                url="https://x",
                method="html",
                seller="s",
                title="t",
                price_rial=86_000_000,
                stock_state="in_stock",
                conditions={},
                identifiers={},
                validity=validity,
                is_own_store=False,
                is_own_channel=False,
                evidence_ids=[],
            )
        )
    return observation_id


async def test_floor_safety_and_evidence_completeness(db: Database) -> None:
    variants = await _variants(db, 6, "ssd")
    good = await _rec(db, variants[0], qualifying=[await _valid_observation(db, variants[0])])
    await _rec(
        db,
        variants[1],
        qualifying=[await _valid_observation(db, variants[1], validity="suspect_unit")],
    )
    await _rec(db, variants[2], qualifying=[])
    await _rec(db, variants[3], outcome="hold")  # not actionable: not counted
    approved = await _decision(db, variants[0], good, applied=83_000_000, override_reason="کمپین")
    rec4 = await _rec(db, variants[4], qualifying=[await _valid_observation(db, variants[4])])
    rejected = await _decision(db, variants[4], rec4, applied=82_000_000, override_reason="رقابت")
    rec5 = await _rec(db, variants[5], qualifying=[await _valid_observation(db, variants[5])])
    self_approved = await _decision(
        db, variants[5], rec5, actor="pilot-admin", applied=83_500_000, override_reason="پایان فصل"
    )
    async with db.tenant_session(TENANT_A) as session:
        for decision, verdict, actor, reason in (
            (approved, "approved", "pilot-admin", "تأیید کمپین"),
            (rejected, "rejected", "pilot-admin", "مجاز نیست"),
            (self_approved, "self_approved", "pilot-admin", "پایان فصل"),
        ):
            session.add(
                OverrideReviewRow(
                    id=new_id(),
                    tenant_id=TENANT_A,
                    decision_id=decision,
                    verdict=verdict,
                    reason=reason,
                    actor_subject=actor,
                    actor=actor,
                )
            )
    async with api_client(db) as client:
        report = (
            await client.get(
                "/reports/pilot", params={"from": str(TODAY), "to": str(TODAY)}, headers=EXPERT_AUTH
            )
        ).json()
    floor = report["floor_safety"]
    assert (floor["below_floor_suggestions"], floor["target"]) == (0, 0)
    assert floor["recommendations"] == 6
    overrides = {o["decision_id"]: o for o in floor["overrides"]}
    assert overrides[str(approved)]["verdict"] == "approved"
    assert overrides[str(approved)]["approver"] == "pilot-admin"
    assert overrides[str(approved)]["request_reason"] == "کمپین"
    assert overrides[str(approved)]["review_reason"] == "تأیید کمپین"
    assert overrides[str(rejected)]["verdict"] == "rejected"
    assert overrides[str(self_approved)]["requested_by"] == "pilot-admin"
    assert floor["self_approved"] == 1

    evidence = report["evidence_completeness"]
    assert (evidence["actionable"], evidence["complete"]) == (5, 3)
    assert evidence["completeness_pct"] == 60.0
    assert len(evidence["non_compliant_ids"]) == 2
    assert evidence["target_pct"] == 100.0


# --- 13.3 review time ------------------------------------------------------------------------------


async def _reviews(db: Database, category: str, minutes: list[float]) -> None:
    variants = await _variants(db, len(minutes), category)
    for variant, spent in zip(variants, minutes, strict=True):
        rec = await _rec(db, variant, created=NOW - timedelta(hours=1))
        decided = NOW - timedelta(minutes=10)
        decision = await _decision(db, variant, rec, at=decided)
        async with db.tenant_session(TENANT_A) as session:
            session.add(
                ReviewSessionRow(
                    id=new_id(),
                    tenant_id=TENANT_A,
                    variant_id=variant,
                    recommendation_id=rec,
                    user_subject="pilot-expert",
                    username="pilot-expert",
                    opened_at=decided - timedelta(minutes=spent),
                    last_activity_at=decided,
                    closed_at=decided,
                    close_reason="decision",
                    decision_id=decision,
                )
            )


async def test_review_time_reduction_on_the_category_mix(db: Database) -> None:
    await _reviews(db, "gpu", [2.0] * 20 + [3.0] * 10 + [4.0] * 20)  # median 3 min
    await _reviews(db, "ssd", [1.0] * 20 + [2.0] * 10 + [3.0] * 20)  # median 2 min
    async with api_client(db) as client:
        for category, minutes in (("gpu", 8), ("ssd", 4)):
            response = await client.put(
                f"/reports/baselines/{category}",
                json={"median_minutes": minutes},
                headers=ADMIN_AUTH,
            )
            assert response.status_code == 200
        report = (
            await client.get(
                "/reports/pilot", params={"from": str(TODAY), "to": str(TODAY)}, headers=EXPERT_AUTH
            )
        ).json()
    review = report["review_time"]
    assert review["decisions"] == 100
    assert review["low_sample"] is False
    assert review["weighted_baseline_seconds"] == 360
    assert review["weighted_measured_seconds"] == 150
    assert round(review["reduction_pct"]) == 58
    assert review["target_pct"] == 50.0
    gpu = next(c for c in review["categories"] if c["category"] == "gpu")
    assert (gpu["median_seconds"], gpu["p90_seconds"], gpu["baseline_seconds"]) == (180, 240, 480)


async def test_small_sample_is_labelled(db: Database) -> None:
    await _reviews(db, "ram", [2.0] * 12)
    async with api_client(db) as client:
        report = (
            await client.get(
                "/reports/pilot", params={"from": str(TODAY), "to": str(TODAY)}, headers=EXPERT_AUTH
            )
        ).json()
    review = report["review_time"]
    assert (review["decisions"], review["low_sample"]) == (12, True)
    assert review["reduction_pct"] is None
    assert review["categories_without_baseline"] == ["ram"]


# --- 13.4 weekly report ----------------------------------------------------------------------------


async def test_weekly_report_with_verification_reliability(db: Database) -> None:
    week_start = TODAY - timedelta(days=TODAY.weekday())
    reported_at = datetime.combine(week_start, datetime.min.time(), tzinfo=UTC) + timedelta(hours=1)
    variants = await _variants(db, 40, "ssd", tier="A")
    for n, variant in enumerate(variants):
        qualifying = [await _valid_observation(db, variant)] if n < 30 else []
        rec = await _rec(
            db, variant, qualifying=qualifying, created=reported_at - timedelta(minutes=30)
        )
        decision = await _decision(
            db, variant, rec, at=reported_at - timedelta(minutes=10), applied=86_000_000
        )
        async with db.tenant_session(TENANT_A) as session:
            session.add(
                DecisionOutcomeRow(
                    id=new_id(),
                    tenant_id=TENANT_A,
                    decision_id=decision,
                    stage="reported_done",
                    occurred_at=reported_at,
                    actor="pilot-expert",
                )
            )
            if n < 36:
                session.add(
                    DecisionOutcomeRow(
                        id=new_id(),
                        tenant_id=TENANT_A,
                        decision_id=decision,
                        stage="observed_on_site",
                        occurred_at=reported_at + timedelta(minutes=30),
                        observation_id=new_id(),
                        delay_seconds=30 * 60,
                    )
                )
            if n < 10:
                session.add(
                    DecisionOutcomeRow(
                        id=new_id(),
                        tenant_id=TENANT_A,
                        decision_id=decision,
                        stage="reflected_in_channel",
                        occurred_at=reported_at + timedelta(hours=5),
                        observation_id=new_id(),
                        delay_seconds=5 * 3600,
                    )
                )
    async with db.tenant_session(TENANT_A) as session:
        for task, result in (
            ("extract_attributes", "ok"),
            ("extract_attributes", "invalid"),
            ("rephrase_explanation", "ok"),
        ):
            session.add(
                LLMCallRow(
                    id=new_id(),
                    tenant_id=TENANT_A,
                    task=task,
                    provider="anthropic",
                    model="claude-sonnet-5-5"
                    if task != "rephrase_explanation"
                    else "claude-haiku-5-5",
                    template_version="v1",
                    input_tokens=1_000,
                    output_tokens=200,
                    latency_ms=900,
                    result=result,
                    correlation_id="c",
                    created_at=reported_at,
                )
            )

    async def weekly() -> dict[str, Any]:
        async with api_client(db) as client:
            response = await client.get(
                "/reports/weekly", params={"week_start": str(week_start)}, headers=EXPERT_AUTH
            )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    report = await weekly()
    reliability = report["verification_reliability"]
    assert (reliability["value"], reliability["sample"], reliability["target"]) == (90.0, 40, None)
    assert reliability["source"].startswith("decision_outcome")
    assert report["site_delay_seconds"]["median"] == 1800
    assert (
        report["channel_delay_seconds"]["count"],
        report["channel_delay_seconds"]["median"],
    ) == (10, 18_000)
    coverage = report["tier_a_coverage"]
    assert (coverage["value"], coverage["sample"]) == (75.0, 40)
    assert report["recommendation_to_decision_seconds"]["median"] == 1200
    assert {(u["task"], u["calls"], u["ok"]) for u in report["llm"]} == {
        ("extract_attributes", 2, 1),
        ("rephrase_explanation", 1, 1),
    }
    assert all(u["cost_rial"] is None for u in report["llm"])  # no price configured
    assert report["backlog"]
    assert {k["key"] for k in report["kpis"]} >= {
        "tier_a_coverage_pct",
        "verification_reliability_pct",
    }
    assert all("source" in s or "requests" in s for s in report["sources"])

    async with api_client(db) as client:
        patched = await client.patch(
            "/settings",
            json={"kpi_targets": {"verification_reliability_pct": 95}},
            headers=ADMIN_AUTH,
        )
    assert patched.status_code == 200, patched.text
    assert (await weekly())["verification_reliability"]["target"] == 95.0
