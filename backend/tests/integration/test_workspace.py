"""Workspace query API: queue, filters, cards, detail, match queue, review sessions (11.1–11.6)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from pricing_assistant.audit.api import list_events
from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import OutboxEventRow
from pricing_assistant.core.ids import new_id
from pricing_assistant.iam.api import Principal, Role
from pricing_assistant.matching.service import MarketOffer, evaluate, record_attributes
from pricing_assistant.pricing.models import RecommendationRow
from pricing_assistant.sources.api import TrackedOfferRow
from pricing_assistant.sources.offers import suggest_offer
from pricing_assistant.workspace import sessions
from tests.support.api import api_client, auth
from tests.support.pricing import confirm_all_matches, default_rule
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A
from .test_matching_flow import _observe
from .test_pricing_flow import _fetch_all, _setup

pytestmark = pytest.mark.integration

EXPERT = auth(TENANT_A, "expert", username="pilot-expert")
ADMIN = auth(TENANT_A, "admin", username="pilot-admin")
NOW = datetime.now(UTC)


async def _rec(
    db: Database,
    variant: uuid.UUID,
    outcome: str,
    *,
    our: int | None = 90_000_000,
    market: int | None = 86_000_000,
    suggested: int | None = None,
    floor: int | None = 84_000_000,
    reason: str = "above_market",
    age: timedelta = timedelta(0),
) -> uuid.UUID:
    rec_id = new_id()
    async with db.tenant_session(TENANT_A) as session:
        session.add(
            RecommendationRow(
                id=rec_id,
                tenant_id=TENANT_A,
                variant_id=variant,
                outcome=outcome,
                reason_code=reason,
                flags=[],
                suggested_price_rial=suggested,
                our_price_rial=our,
                floor_rial=floor,
                ceiling_rial=None,
                market_ref_rial=market,
                market_ref_observation_id=None,
                median_rial=market,
                qualifying_count=1 if market else 0,
                qualifying_observation_ids=[],
                excluded_outlier_ids=[],
                effective_cost_rial=75_000_000,
                profit_current_rial=None,
                profit_suggested_rial=None,
                explanation="متن آزمایشی",
                observation_ids=[],
                match_version_ids=[],
                outlier_confirmation_ids=[],
                cost_record_id=None,
                cost_component_ids=[],
                rule_version_ids=[],
                inputs={
                    "evaluated_at": (NOW - age).isoformat(),
                    "tier": "A",
                    "our_price_rial": our,
                    "offers": [],
                },
                evaluated_at=NOW - age,
                engine_version="1.0.0",
                created_at=NOW - age,
            )
        )
    return rec_id


async def _queue(db: Database, headers: dict[str, str] = EXPERT, **params: Any) -> dict[str, Any]:
    async with api_client(db) as client:
        response = await client.get("/queue", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _decide(db: Database, rec: uuid.UUID, **body: Any) -> dict[str, Any]:
    async with api_client(db) as client:
        response = await client.post(
            f"/recommendations/{rec}/decisions",
            json={"reason": "test", **body},
            headers=EXPERT,
        )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def _competitor(
    db: Database, variant: uuid.UUID, *, observed: datetime, failed: datetime | None = None
) -> uuid.UUID:
    """A competitor offer with one valid observation at ``observed`` (and a later failure)."""
    source = await seed_source(db, TENANT_A, name=f"S-{variant.hex[-6:]}")
    offer = await seed_offer(
        db,
        TENANT_A,
        source_id=source,
        variant_id=variant,
        url=f"https://www.lioncomputer.com/{variant.hex}",
    )
    async with db.tenant_session(TENANT_A) as session:
        for when, outcome in [(observed, "success")] + ([(failed, "failure")] if failed else []):
            assert when is not None
            attempt = FetchAttemptRow(
                id=new_id(),
                tenant_id=TENANT_A,
                tracked_offer_id=offer,
                source_id=source,
                window_start=when,
                attempt=1,
                trigger="scheduled",
                outcome=outcome,
                error_class=None if outcome == "success" else "network",
                offers_count=1 if outcome == "success" else 0,
                final=True,
                correlation_id="t",
                finished_at=when,
            )
            session.add(attempt)
            await session.flush()
            if outcome == "success":
                session.add(
                    ObservationRow(
                        id=new_id(),
                        tenant_id=TENANT_A,
                        tracked_offer_id=offer,
                        source_id=source,
                        variant_id=variant,
                        fetch_attempt_id=attempt.id,
                        observed_at=when,
                        url="https://www.lioncomputer.com/x",
                        method="html",
                        seller="رقیب",
                        title="SSD",
                        price_rial=86_000_000,
                        stock_state="in_stock",
                        conditions={},
                        identifiers={},
                        validity="valid",
                        is_own_store=False,
                        is_own_channel=False,
                        evidence_ids=[],
                    )
                )
    return offer


async def _catalogue(db: Database) -> dict[str, tuple[uuid.UUID, uuid.UUID]]:
    """Five variants covering every filter dimension; returns name → (variant, rec)."""
    await default_rule(db, TENANT_A)
    made = {}
    for name, tier, category in (
        ("a_conflict", "A", "ssd"),
        ("c_hold", "C", "ssd"),
        ("b_decrease", "B", "ram"),
        ("a_increase", "A", "gpu"),
        ("b_stale", "B", "ram"),
    ):
        made[name] = await seed_variant(db, TENANT_A, sku=name, tier=tier, category=category)
    recs = {
        "a_conflict": await _rec(
            db, made["a_conflict"], "floor_conflict", market=80_000_000, reason="market_below_floor"
        ),
        "c_hold": await _rec(
            db,
            made["c_hold"],
            "hold",
            our=86_000_000,
            reason="within_tolerance",
            age=timedelta(hours=30),
        ),
        "b_decrease": await _rec(db, made["b_decrease"], "decrease", suggested=85_900_000),
        "a_increase": await _rec(
            db,
            made["a_increase"],
            "increase",
            our=80_000_000,
            suggested=85_900_000,
            reason="below_market",
        ),
        "b_stale": await _rec(
            db, made["b_stale"], "insufficient_data", market=None, reason="stale_evidence"
        ),
    }
    await _competitor(db, made["b_stale"], observed=NOW - timedelta(days=2))
    await _competitor(
        db,
        made["b_decrease"],
        observed=NOW - timedelta(minutes=10),
        failed=NOW - timedelta(minutes=5),
    )
    return {name: (made[name], recs[name]) for name in made}


def _skus(body: dict[str, Any]) -> list[str]:
    return [item["sku"] for item in body["items"]]


# --- 11.1 queue and priority ----------------------------------------------------------------------


async def test_tier_a_floor_conflict_is_on_top_with_score_inputs(db: Database) -> None:
    await _catalogue(db)
    body = await _queue(db)
    assert body["total"] == 5
    first, last = body["items"][0], body["items"][-1]
    assert (first["sku"], first["tier"], first["outcome"]) == ("a_conflict", "A", "floor_conflict")
    assert last["sku"] == "c_hold"
    assert "floor_conflict" in first["alerts"]
    score = first["score"]
    assert score["score"] == score["tier_multiplier"] * (
        score["outcome_weight"] + score["profit_points"] + score["age_points"]
    )
    assert score["tier_multiplier"] == 3
    hold = next(i for i in body["items"] if i["sku"] == "c_hold")
    assert hold["score"]["age_hours"] >= 29  # open for 30 hours
    assert hold["score"]["age_points"] == 24  # capped
    stale = next(i for i in body["items"] if i["sku"] == "b_stale")
    assert (stale["market_ref_rial"], stale["market_label"]) == (None, "stale")
    assert "stale_data" in stale["alerts"]
    failing = next(i for i in body["items"] if i["sku"] == "b_decrease")
    assert "source_failure" in failing["alerts"]
    assert all(i["status"] == "needs_review" for i in body["items"])


# --- 11.2 filters and pagination --------------------------------------------------------------------


async def test_every_filter_dimension(db: Database) -> None:
    made = await _catalogue(db)
    await _decide(db, made["b_decrease"][1], type="accept", applied_price_rial=85_900_000)
    await _decide(
        db,
        made["a_increase"][1],
        type="accept_modified",
        applied_price_rial=83_000_000,
        override_reason="ویژه",
    )
    cases: list[tuple[dict[str, Any], set[str]]] = [
        ({"category": "ram"}, {"b_decrease", "b_stale"}),
        ({"category": ["ssd", "gpu"]}, {"a_conflict", "c_hold", "a_increase"}),
        ({"tier": "A"}, {"a_conflict", "a_increase"}),
        ({"outcome": ["hold", "insufficient_data"]}, {"c_hold", "b_stale"}),
        ({"status": "needs_review"}, {"a_conflict", "c_hold", "b_stale"}),
        ({"status": "decided"}, {"b_decrease"}),
        ({"status": "awaiting_override"}, {"a_increase"}),
        ({"source_health": "failing"}, {"b_decrease"}),
        ({"source_health": "stale"}, {"b_stale"}),
        ({"source_health": "attention"}, {"b_decrease", "b_stale"}),
        ({"price_position": "above_market"}, {"a_conflict", "b_decrease"}),
        ({"price_position": "below_market"}, {"a_increase"}),
        ({"tier": "B", "status": "decided"}, {"b_decrease"}),
    ]
    for params, expected in cases:
        body = await _queue(db, **params)
        assert set(_skus(body)) == expected, params
        assert body["total"] == len(expected)


async def test_cursor_pagination_walks_every_item_once(db: Database) -> None:
    await _catalogue(db)
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = await _queue(db, **params)
        seen += _skus(body)
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == _skus(await _queue(db, limit=50))
    assert len(seen) == len(set(seen)) == 5
    async with api_client(db) as client:
        bad = await client.get("/queue", params={"cursor": "%%%"}, headers=EXPERT)
    assert bad.status_code == 422


# --- 11.3 summary cards ----------------------------------------------------------------------------


async def test_card_counts_equal_their_filtered_queue(db: Database) -> None:
    made = await _catalogue(db)
    await _decide(
        db,
        made["a_increase"][1],
        type="accept_modified",
        applied_price_rial=83_000_000,
        override_reason="ویژه",
    )
    for headers, is_admin in ((EXPERT, False), (ADMIN, True)):
        async with api_client(db) as client:
            cards = (await client.get("/queue/summary", headers=headers)).json()
            match_queue = (await client.get("/match-queue", headers=headers)).json()
        keys = [c["key"] for c in cards]
        assert ("overrides_awaiting_approval" in keys) is is_admin
        assert [c["key"] for c in cards if c["primary"]] == ["open_decisions"]
        for card in cards:
            if card["target"] == "matches":
                expected = len(match_queue["matches"]) + len(match_queue["suggested_offers"])
            else:
                expected = (await _queue(db, headers, **card["filter"]))["total"]
            assert card["count"] == expected, card["key"]
    counts = {c["key"]: c["count"] for c in cards}
    assert counts["above_market"] == 2
    assert counts["floor_conflicts"] == 1
    assert counts["overrides_awaiting_approval"] == 1


# --- 11.4 detail -----------------------------------------------------------------------------------


async def test_evidence_row_content(db: Database, redis_client: Redis) -> None:
    harness, variant, offers, _ = await _setup(
        db, redis_client, [86_000_000, 87_000_000, 60_000_000]
    )
    await _fetch_all(harness, offers, datetime.now(UTC))
    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    async with api_client(db) as client:
        response = await client.get(f"/queue/{variant}", headers=EXPERT)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["item"]["outcome"] == "decrease"
    assert detail["explanation"]
    assert detail["item"]["floor_rial"] == 84_000_000
    rows = detail["evidence"]
    assert len(rows) == 3
    for row in rows:
        assert row["price_rial"] > 0
        assert row["stock_state"] == "in_stock"
        assert row["observed_at"]
        assert 0 <= row["age_seconds"] < 600
        assert row["match_state"] == "confirmed"
        assert row["url"].startswith("https://www.lioncomputer.com/p")
        assert row["freshness"] == "fresh"
        assert row["evidence"]
        assert all(link["url"] and "X-Amz-Signature" in link["url"] for link in row["evidence"])
    cheap, reference, other = rows  # sorted by price
    assert cheap["price_rial"] == 60_000_000
    assert (cheap["qualifies"], cheap["flags"], cheap["reasons"]) == (
        False,
        ["price_outlier"],
        ["price_outlier"],
    )
    assert cheap["reasons_fa"] == ["قیمت پرت؛ تا تأیید کارشناس لحاظ نمی‌شود"]
    assert (reference["qualifies"], reference["is_market_reference"]) == (True, True)
    assert (other["qualifies"], other["is_market_reference"]) == (True, False)

    async with api_client(db) as client:
        missing = await client.get(f"/queue/{uuid.uuid4()}", headers=EXPERT)
    assert missing.status_code == 404


# --- 11.5 match queue ------------------------------------------------------------------------------


async def test_side_by_side_compare_and_match_decision(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)  # Samsung 990 PRO 1TB, Avajang 36 months
    source = await seed_source(db, TENANT_A)
    offer = await seed_offer(db, TENANT_A, source_id=source, variant_id=variant)
    observation = await _observe(db, offer, title="SSD سامسونگ 990 PRO 2TB")
    async with db.tenant_session(TENANT_A) as session:
        await record_attributes(session, TENANT_A, observation)
        await evaluate(session, TENANT_A, MarketOffer(offer, "لیون"))

    async with api_client(db) as client:
        queue = (await client.get("/match-queue", headers=EXPERT)).json()
    [pending] = queue["matches"]
    assert pending["state"] == "needs_review"
    assert pending["title"] == "SSD سامسونگ 990 PRO 2TB"
    by_name = {a["name"]: a for a in pending["attributes"]}
    assert by_name["capacity"] == {
        "name": "capacity",
        "ours": "1TB",
        "theirs": "2TB",
        "source": "rule",
        "state": "different",
    }
    assert by_name["brand"]["state"] == "equal"
    assert by_name["model"]["state"] == "equal"

    async with api_client(db) as client:
        no_reason = await client.post(
            f"/matches/{pending['match_version_id']}/decision",
            json={"action": "reject"},
            headers=EXPERT,
        )
        rejected = await client.post(
            f"/matches/{pending['match_version_id']}/decision",
            json={"action": "reject", "reason": "ظرفیت متفاوت"},
            headers=EXPERT,
        )
        after = (await client.get("/match-queue", headers=EXPERT)).json()
    assert no_reason.status_code == 422
    assert rejected.status_code == 200
    assert (rejected.json()["state"], rejected.json()["decided_by"]) == ("rejected", "human")
    assert after["matches"] == []
    async with db.tenant_session(TENANT_A) as session:
        types = (await session.scalars(select(OutboxEventRow.type))).all()
    assert "match.changed" in types  # triggers the recompute


async def test_confirm_suggested_url_schedules_and_audits(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A)
    async with db.tenant_session(TENANT_A) as session:
        suggestion = await suggest_offer(
            session,
            tenant_id=TENANT_A,
            suggested_by="llm",
            source_id=source,
            variant_id=variant,
            url="https://www.lioncomputer.com/product/suggested",
            rationale="همان مدل و ظرفیت",
        )
    assert suggestion is not None
    async with api_client(db) as client:
        queue = (await client.get("/match-queue", headers=EXPERT)).json()
        [shown] = queue["suggested_offers"]
        assert (shown["suggested_by"], shown["rationale"]) == ("llm", "همان مدل و ظرفیت")
        confirmed = await client.post(
            f"/tracked-offers/{shown['tracked_offer_id']}/review",
            json={"decision": "confirm"},
            headers=EXPERT,
        )
        after = (await client.get("/match-queue", headers=EXPERT)).json()
    assert confirmed.json()["status"] == "active"
    assert after["suggested_offers"] == []
    async with db.tenant_session(TENANT_A) as session:
        offer = await session.get(TrackedOfferRow, suggestion.id)
        [audit] = await list_events(session, action="source.offer.confirmed")
    assert offer is not None
    assert offer.next_due_at is not None  # scheduled
    assert audit.actor_username == "pilot-expert"


# --- 11.6 review sessions ----------------------------------------------------------------------------


EXPERT_PRINCIPAL = Principal(
    subject="pilot-expert",
    username="pilot-expert",
    tenant_id=TENANT_A,
    roles=frozenset({Role.EXPERT}),
)
OTHER = Principal(
    subject="other", username="other", tenant_id=TENANT_A, roles=frozenset({Role.EXPERT})
)


async def test_review_session_timing(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    t0 = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    async with db.tenant_session(TENANT_A) as session:
        active = await sessions.open_session(
            session, principal=EXPERT_PRINCIPAL, variant_id=variant, recommendation_id=None, now=t0
        )
        await sessions.record_activity(
            session, principal=EXPERT_PRINCIPAL, session_id=active.id, now=t0 + timedelta(minutes=5)
        )
        done = await sessions.close_session(
            session,
            principal=EXPERT_PRINCIPAL,
            session_id=active.id,
            reason=sessions.CloseReason.DECISION,
            now=t0 + timedelta(minutes=8),
        )
    assert (done.close_reason, done.duration_seconds) == ("decision", 8 * 60)

    async with db.tenant_session(TENANT_A) as session:
        abandoned = await sessions.open_session(
            session, principal=EXPERT_PRINCIPAL, variant_id=variant, recommendation_id=None, now=t0
        )
        late = await sessions.close_session(
            session,
            principal=EXPERT_PRINCIPAL,
            session_id=abandoned.id,
            reason=sessions.CloseReason.LEFT,
            now=t0 + timedelta(minutes=40),
        )
    assert (late.close_reason, late.duration_seconds) == ("idle", 15 * 60)

    async with db.tenant_session(TENANT_A) as session:
        forgotten = await sessions.open_session(
            session, principal=EXPERT_PRINCIPAL, variant_id=variant, recommendation_id=None, now=t0
        )
    assert await sessions.close_idle(db, now=t0 + timedelta(minutes=14)) == 0
    assert await sessions.close_idle(db, now=t0 + timedelta(minutes=16)) == 1
    async with db.tenant_session(TENANT_A) as session:
        closed = await session.get(sessions.ReviewSessionRow, forgotten.id)
        assert closed is not None
        assert (closed.close_reason, closed.duration_seconds) == ("idle", 15 * 60)
        with pytest.raises(Exception, match="not found"):
            await sessions.record_activity(session, principal=OTHER, session_id=forgotten.id)


async def test_review_session_api(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    async with api_client(db) as client:
        opened = await client.post(
            "/review-sessions", json={"variant_id": str(variant)}, headers=EXPERT
        )
        assert opened.status_code == 201
        session_id = opened.json()["id"]
        assert (
            await client.post(f"/review-sessions/{session_id}/activity", headers=EXPERT)
        ).status_code == 200
        closed = await client.post(
            f"/review-sessions/{session_id}/close", json={"reason": "left"}, headers=EXPERT
        )
        again = await client.post(
            f"/review-sessions/{session_id}/close", json={"reason": "left"}, headers=EXPERT
        )
    assert closed.json()["close_reason"] == "left"
    assert closed.json()["duration_seconds"] >= 0
    assert again.status_code == 409
