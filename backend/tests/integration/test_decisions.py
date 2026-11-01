"""Decisions, below-floor overrides, outcome tracking and history (tasks 10.1–10.6, 10.8)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from dramatiq.brokers.stub import StubBroker
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from pricing_assistant.audit.api import list_events
from pricing_assistant.collection.events import ObservationRecorded
from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.core import tenant_settings
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.ids import new_id
from pricing_assistant.decisions.consumers import on_observation_recorded
from pricing_assistant.decisions.models import DecisionOutcomeRow
from pricing_assistant.decisions.service import mark_overdue
from pricing_assistant.pricing.service import current_recommendation
from pricing_assistant.scheduler import build_jobs
from pricing_assistant.sources.api import TrackedOfferRow
from tests.support.api import api_client, auth
from tests.support.pricing import confirm_all_matches
from tests.support.seed import seed_offer, seed_source

from .conftest import TENANT_A
from .test_pricing_flow import _fetch_all, _setup

pytestmark = pytest.mark.integration

EXPERT = auth(TENANT_A, "expert", username="pilot-expert")
ADMIN_AUTH = auth(TENANT_A, "admin", username="pilot-admin")
SUGGESTED, FLOOR, OLD_PRICE = 85_500_000, 84_000_000, 89_000_000


async def _recommendation(db: Database, redis: Redis) -> tuple[uuid.UUID, uuid.UUID, Any]:
    """A current ``decrease`` recommendation: suggested 85.5M, floor 84M, our price 89M."""
    harness, variant, offers, connector = await _setup(db, redis, [86_000_000])
    await _fetch_all(harness, offers, datetime.now(UTC))
    await confirm_all_matches(db, TENANT_A)
    await harness.settle()
    async with db.tenant_session(TENANT_A) as session:
        rec = await current_recommendation(session, variant)
    assert rec is not None
    assert (rec.outcome, rec.suggested_price_rial, rec.floor_rial) == ("decrease", SUGGESTED, FLOOR)
    return variant, rec.id, (harness, offers, connector)


async def _decide(
    db: Database, rec: uuid.UUID, headers: dict[str, str] = EXPERT, **body: Any
) -> Any:
    async with api_client(db) as client:
        return await client.post(f"/recommendations/{rec}/decisions", json=body, headers=headers)


async def _post(db: Database, path: str, headers: dict[str, str] = EXPERT, **body: Any) -> Any:
    async with api_client(db) as client:
        return await client.post(path, json=body or None, headers=headers)


def _code(response: Any) -> str:
    return str(response.json()["type"]).rsplit(":", 1)[-1]


# --- 10.1 append-only -------------------------------------------------------------------------


@pytest.mark.parametrize("table", ["decision", "override_review", "decision_outcome"])
@pytest.mark.parametrize("verb", ["UPDATE {t} SET id = id", "DELETE FROM {t}"])
async def test_decision_tables_are_append_only(db: Database, table: str, verb: str) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text(verb.format(t=table)))


# --- 10.2 recording ---------------------------------------------------------------------------


async def test_decision_without_reason_is_refused(db: Database, redis_client: Redis) -> None:
    _, rec, _ = await _recommendation(db, redis_client)
    response = await _decide(db, rec, type="accept", reason="   ", applied_price_rial=SUGGESTED)
    assert response.status_code == 422
    assert response.json()["message_fa"] == "برای ثبت، یادداشت تصمیم را وارد کنید."


async def test_accept_is_recorded_with_actor_and_audit(db: Database, redis_client: Redis) -> None:
    _, rec, _ = await _recommendation(db, redis_client)
    wrong = await _decide(db, rec, type="accept", reason="ok", applied_price_rial=85_000_000)
    assert _code(wrong) == "accept_requires_suggested_price"
    missing = await _decide(db, rec, type="accept_modified", reason="ok")
    assert _code(missing) == "applied_price_required"

    response = await _decide(
        db, rec, type="accept", reason="هم‌راستا با بازار", applied_price_rial=SUGGESTED
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["type"], body["status"], body["actor"]) == ("accept", "decided", "pilot-expert")
    assert (body["recommendation_id"], body["reason"]) == (str(rec), "هم‌راستا با بازار")
    assert body["below_floor_override"] is False
    async with db.tenant_session(TENANT_A) as session:
        [audit] = await list_events(session, action="decision.recorded")
    assert audit.actor_username == "pilot-expert"

    again = await _decide(db, rec, type="reject", reason="second thoughts")
    assert (again.status_code, _code(again)) == (409, "already_decided")


async def test_stale_submission_is_refused_with_the_current_version(
    db: Database, redis_client: Redis
) -> None:
    variant, rec, (harness, offers, connector) = await _recommendation(db, redis_client)
    connector.prices[offers[0]] = 85_000_000  # a new observation supersedes the recommendation
    await _fetch_all(harness, offers, datetime.now(UTC) + timedelta(hours=1))
    async with db.tenant_session(TENANT_A) as session:
        current = await current_recommendation(session, variant)
    assert current is not None
    assert current.id != rec

    response = await _decide(db, rec, type="reject", reason="بازار پایین‌تر است")
    assert response.status_code == 409
    assert _code(response) == "recommendation_superseded"
    assert response.json()["current_recommendation_id"] == str(current.id)


# --- 10.3 below-floor override ----------------------------------------------------------------


async def _below_floor(db: Database, rec: uuid.UUID, headers: dict[str, str] = EXPERT) -> Any:
    return await _decide(
        db,
        rec,
        headers,
        type="accept_modified",
        reason="رقابت با فروشنده اصلی",
        applied_price_rial=83_000_000,
        override_reason="فروش ویژه پایان فصل",
    )


async def test_below_floor_price_waits_for_admin_approval(
    db: Database, redis_client: Redis
) -> None:
    _, rec, _ = await _recommendation(db, redis_client)
    no_reason = await _decide(
        db, rec, type="accept_modified", reason="x", applied_price_rial=83_000_000
    )
    assert _code(no_reason) == "override_reason_required"

    decision = (await _below_floor(db, rec)).json()
    assert decision["below_floor_override"] is True
    assert decision["status"] == "override_pending"
    assert decision["floor_rial"] == FLOOR

    early = await _post(db, f"/decisions/{decision['id']}/reported-done")
    assert (early.status_code, _code(early)) == (409, "override_not_approved")
    assert early.json()["message_fa"] == "قیمت زیر کف نیازمند تأیید مدیر است."

    by_expert = await _post(
        db, f"/decisions/{decision['id']}/override-review", decision="approve", reason="ok"
    )
    assert by_expert.status_code == 403

    approved = await _post(
        db,
        f"/decisions/{decision['id']}/override-review",
        ADMIN_AUTH,
        decision="approve",
        reason="کمپین تأییدشده",
    )
    assert approved.status_code == 200, approved.text
    review = approved.json()["override_review"]
    assert (review["verdict"], review["actor"], review["reason"]) == (
        "approved",
        "pilot-admin",
        "کمپین تأییدشده",
    )
    done = await _post(db, f"/decisions/{decision['id']}/reported-done")
    assert done.json()["status"] == "awaiting_verification"
    async with db.tenant_session(TENANT_A) as session:
        actions = sorted(
            e.action for e in await list_events(session) if e.action.startswith("decision.")
        )
    assert actions == [
        "decision.override.approved",
        "decision.override.requested",
        "decision.recorded",
        "decision.reported_done",
    ]


async def test_rejected_override_needs_a_superseding_decision(
    db: Database, redis_client: Redis
) -> None:
    _, rec, _ = await _recommendation(db, redis_client)
    decision = (await _below_floor(db, rec)).json()
    async with db.tenant_session(TENANT_A) as session:
        before = (await session.scalars(select(DecisionOutcomeRow))).all()
    rejected = await _post(
        db,
        f"/decisions/{decision['id']}/override-review",
        ADMIN_AUTH,
        decision="reject",
        reason="زیر کف مجاز نیست",
    )
    assert rejected.json()["status"] == "override_rejected"
    assert (await _post(db, f"/decisions/{decision['id']}/reported-done")).status_code == 409
    again = await _post(
        db,
        f"/decisions/{decision['id']}/override-review",
        ADMIN_AUTH,
        decision="approve",
        reason="changed my mind",
    )
    assert _code(again) == "override_already_reviewed"

    replacement = await _decide(
        db,
        rec,
        type="accept_modified",
        reason="قیمت روی کف",
        applied_price_rial=FLOOR,
        supersedes_decision_id=decision["id"],
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["status"] == "decided"
    old = await _post(db, f"/decisions/{decision['id']}/reported-done")
    assert _code(old) == "decision_superseded"
    async with db.tenant_session(TENANT_A) as session:
        assert (await session.scalars(select(DecisionOutcomeRow))).all() == before == []


async def test_admins_own_override_is_self_approved(db: Database, redis_client: Redis) -> None:
    _, rec, _ = await _recommendation(db, redis_client)
    decision = (await _below_floor(db, rec, ADMIN_AUTH)).json()
    assert decision["override_review"]["verdict"] == "self_approved"
    assert decision["status"] == "decided"
    done = await _post(db, f"/decisions/{decision['id']}/reported-done", ADMIN_AUTH)
    assert done.status_code == 200
    async with db.tenant_session(TENANT_A) as session:
        assert await list_events(session, action="decision.override.self_approved")


# --- 10.4 correction ------------------------------------------------------------------------


async def test_correction_supersedes_and_keeps_both(db: Database, redis_client: Redis) -> None:
    variant, rec, _ = await _recommendation(db, redis_client)
    first = (
        await _decide(db, rec, type="accept", reason="ok", applied_price_rial=SUGGESTED)
    ).json()
    corrected = await _decide(
        db,
        rec,
        type="accept_modified",
        reason="قیمت را ۸۵٬۹۰۰٬۰۰۰ وارد کرده بودم",
        applied_price_rial=85_900_000,
        supersedes_decision_id=first["id"],
    )
    assert corrected.status_code == 201
    twice = await _decide(db, rec, type="reject", reason="x", supersedes_decision_id=first["id"])
    assert _code(twice) == "decision_superseded"

    async with api_client(db) as client:
        history = (await client.get(f"/variants/{variant}/history", headers=EXPERT)).json()
    decisions = [d for item in history for d in item["decisions"]]
    assert [(d["id"], d["superseded_by"]) for d in decisions] == [
        (first["id"], corrected.json()["id"]),
        (corrected.json()["id"], None),
    ]
    assert decisions[1]["supersedes_decision_id"] == first["id"]


# --- 10.5 outcome stages ----------------------------------------------------------------------


async def _own_observation(
    db: Database, offer: uuid.UUID, price: int, at: datetime, *, channel: bool = False
) -> None:
    async with db.tenant_session(TENANT_A) as session:
        tracked = await session.get(TrackedOfferRow, offer)
        assert tracked is not None
        attempt = FetchAttemptRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=tracked.source_id,
            window_start=at,
            attempt=1,
            trigger="scheduled",
            outcome="success",
            offers_count=1,
            final=True,
            correlation_id="own",
        )
        session.add(attempt)
        await session.flush()
        observation = ObservationRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=tracked.source_id,
            variant_id=tracked.variant_id,
            fetch_attempt_id=attempt.id,
            observed_at=at,
            url=tracked.url,
            method="html",
            seller="ما",
            title="SSD",
            price_rial=price,
            stock_state="in_stock",
            conditions={},
            identifiers={},
            validity="valid",
            is_own_store=not channel,
            is_own_channel=channel,
            evidence_ids=[],
        )
        session.add(observation)
        await session.flush()
        event = ObservationRecorded(
            observation_ids=[observation.id],
            tracked_offer_id=offer,
            variant_id=tracked.variant_id,
            source_id=tracked.source_id,
            is_own_store=not channel,
            is_own_channel=channel,
        )
        envelope = EventEnvelope(
            event_id=new_id(),
            type=event.event_type,
            version=1,
            tenant_id=TENANT_A,
            occurred_at=at,
            correlation_id="own",
            payload=event.model_dump(mode="json"),
        )
        await on_observation_recorded(session, envelope)


async def _stages(db: Database, decision_id: str) -> dict[str, DecisionOutcomeRow]:
    async with db.tenant_session(TENANT_A) as session:
        rows = (
            await session.scalars(
                select(DecisionOutcomeRow).where(
                    DecisionOutcomeRow.decision_id == uuid.UUID(decision_id)
                )
            )
        ).all()
    return {r.stage: r for r in rows}


async def _reported(db: Database, redis: Redis) -> tuple[uuid.UUID, str, uuid.UUID, uuid.UUID]:
    variant, rec, _ = await _recommendation(db, redis)
    store = await seed_source(db, TENANT_A, name="Our store")
    channel = await seed_source(db, TENANT_A, name="Torob")
    own = await seed_offer(
        db,
        TENANT_A,
        source_id=store,
        variant_id=variant,
        url="https://www.lioncomputer.com/own",
        own_store=True,
    )
    listing = await seed_offer(
        db,
        TENANT_A,
        source_id=channel,
        variant_id=variant,
        url="https://www.lioncomputer.com/torob",
        own_channel=True,
    )
    decision = (
        await _decide(db, rec, type="accept", reason="ok", applied_price_rial=SUGGESTED)
    ).json()
    done = await _post(db, f"/decisions/{decision['id']}/reported-done")
    assert done.status_code == 200
    assert done.json()["status"] == "awaiting_verification"
    return variant, decision["id"], own, listing


async def test_reported_change_is_verified_on_site_and_channel_separately(
    db: Database, redis_client: Redis
) -> None:
    _, decision, own, listing = await _reported(db, redis_client)
    reported_at = (await _stages(db, decision))["reported_done"].occurred_at

    await _own_observation(db, own, OLD_PRICE, reported_at + timedelta(minutes=5))
    stages = await _stages(db, decision)
    assert set(stages) == {"reported_done"}  # still the old price: not verified

    await _own_observation(db, own, SUGGESTED, reported_at + timedelta(minutes=20))
    stages = await _stages(db, decision)
    assert stages["observed_on_site"].delay_seconds == 20 * 60
    assert stages["observed_on_site"].observation_id is not None

    # channel lag: Torob still shows the old price after the 2 h window
    await _own_observation(db, listing, OLD_PRICE, reported_at + timedelta(hours=3), channel=True)
    assert await mark_overdue(db, now=reported_at + timedelta(hours=3)) == 0
    stages = await _stages(db, decision)
    assert "reflected_in_channel" not in stages
    assert "verification_overdue" not in stages

    await _own_observation(db, listing, SUGGESTED, reported_at + timedelta(hours=5), channel=True)
    stages = await _stages(db, decision)
    assert stages["reflected_in_channel"].delay_seconds == 5 * 3600  # reported separately
    async with api_client(db) as client:
        body = (await client.get(f"/decisions/{decision}", headers=EXPERT)).json()
    assert body["status"] == "verified"
    assert [o["stage"] for o in body["outcomes"]] == [
        "reported_done",
        "observed_on_site",
        "reflected_in_channel",
    ]


# --- 10.6 verification timeout ----------------------------------------------------------------


async def test_unverified_change_becomes_overdue_after_the_window(
    db: Database, redis_client: Redis
) -> None:
    _, decision, _, _ = await _reported(db, redis_client)
    async with db.tenant_session(TENANT_A) as session:
        assert (await tenant_settings.load(session, TENANT_A)).verification_window_minutes == 120
    reported_at = (await _stages(db, decision))["reported_done"].occurred_at

    assert await mark_overdue(db, now=reported_at + timedelta(minutes=119)) == 0
    assert await mark_overdue(db, now=reported_at + timedelta(minutes=121)) == 1
    assert await mark_overdue(db, now=reported_at + timedelta(minutes=180)) == 0  # once only
    async with api_client(db) as client:
        body = (await client.get(f"/decisions/{decision}", headers=EXPERT)).json()
    assert body["status"] == "verification_overdue"
    async with db.tenant_session(TENANT_A) as session:
        assert await list_events(session, action="decision.verification_overdue")


# --- 10.8 history -----------------------------------------------------------------------------


async def test_history_lists_recommendations_decisions_reviews_and_outcomes(
    db: Database, redis_client: Redis
) -> None:
    variant, rec, _ = await _recommendation(db, redis_client)
    decision = (await _below_floor(db, rec)).json()
    await _post(
        db,
        f"/decisions/{decision['id']}/override-review",
        ADMIN_AUTH,
        decision="approve",
        reason="کمپین",
    )
    await _post(db, f"/decisions/{decision['id']}/reported-done")

    async with api_client(db) as client:
        response = await client.get(f"/variants/{variant}/history", headers=EXPERT)
    assert response.status_code == 200
    history = response.json()
    times = [item["recommendation"]["evaluated_at"] for item in history]
    assert times == sorted(times)
    assert len(history) >= 2  # the pending_review version, then the decrease
    [entry] = [item for item in history if item["recommendation"]["id"] == str(rec)]
    [shown] = entry["decisions"]
    assert (shown["actor"], shown["reason"], shown["applied_price_rial"]) == (
        "pilot-expert",
        "رقابت با فروشنده اصلی",
        83_000_000,
    )
    assert shown["override_review"]["verdict"] == "approved"
    assert [o["stage"] for o in shown["outcomes"]] == ["reported_done"]
    assert all(not item["decisions"] for item in history if item is not entry)


async def test_scheduler_runs_the_verification_timer(db: Database) -> None:
    jobs = {job.name: job for job in build_jobs(db, StubBroker())}
    assert jobs["decisions.verification_overdue"].interval_seconds == 60.0
    assert await jobs["decisions.verification_overdue"].run() == 0
