import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from pricing_assistant.audit.api import list_events
from pricing_assistant.collection.events import ObservationRecorded
from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.core.consumer import consume
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import Conflict, ValidationFailed
from pricing_assistant.core.events import OutboxEventRow, publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.matching.consumers import on_attributes_updated, on_observation_recorded
from pricing_assistant.matching.models import DecisionSource, MatchVersionRow
from pricing_assistant.matching.service import (
    ExpertAction,
    MarketOffer,
    current_match,
    decide,
    evaluate,
    history,
    record_attributes,
)
from pricing_assistant.sources.api import TrackedOfferRow
from tests.support.seed import ADMIN, seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration


async def _observe(
    db: Database,
    offer: uuid.UUID,
    *,
    title: str,
    warranty: str | None = "گارانتی ۳۶ ماهه آواژنگ",
    identifiers: dict[str, str] | None = None,
    seller: str | None = "لیون",
) -> ObservationRow:
    async with db.tenant_session(TENANT_A) as session:
        tracked = await session.get(TrackedOfferRow, offer)
        assert tracked is not None
        attempt = FetchAttemptRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=tracked.source_id,
            window_start=datetime.now(UTC),
            attempt=1,
            trigger="scheduled",
            outcome="success",
            offers_count=1,
            final=True,
            correlation_id="c",
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
            observed_at=datetime.now(UTC),
            url=tracked.url,
            method="html",
            seller=seller,
            title=title,
            price_rial=86_000_000,
            stock_state="in_stock",
            conditions={"warranty": warranty} if warranty else {},
            identifiers=identifiers or {},
            validity="valid",
            is_own_store=False,
            is_own_channel=False,
            evidence_ids=[],
        )
        session.add(observation)
    return observation


async def _setup(db: Database, **variant: object) -> tuple[uuid.UUID, uuid.UUID]:
    variant_id = await seed_variant(db, TENANT_A, **variant)  # type: ignore[arg-type]
    source = await seed_source(db, TENANT_A)
    return await seed_offer(db, TENANT_A, source_id=source, variant_id=variant_id), variant_id


async def _match(db: Database, observation: ObservationRow) -> MatchVersionRow | None:
    async with db.tenant_session(TENANT_A) as session:
        await record_attributes(session, TENANT_A, observation)
        return await evaluate(session, TENANT_A, MarketOffer(observation.tracked_offer_id, "لیون"))


async def test_exact_identifier_match_is_auto_confirmed_and_audited(db: Database) -> None:
    offer, _ = await _setup(db, mpn="MZ-V9P1T0BW")
    observation = await _observe(
        db, offer, title="SSD سامسونگ 990 PRO 1TB", identifiers={"mpn": "MZ-V9P1T0BW"}
    )
    version = await _match(db, observation)
    assert version is not None
    assert (version.state, version.decided_by) == ("confirmed", "rule")
    async with db.tenant_session(TENANT_A) as session:
        [audit] = await list_events(session, action="match.auto_confirmed")
    assert audit.target_id == str(version.id)


async def test_invalid_gtin_goes_to_confirmation_queue(db: Database) -> None:
    offer, _ = await _setup(db, gtin="8806094215039")
    observation = await _observe(
        db, offer, title="SSD سامسونگ 990 PRO 1TB", identifiers={"gtin13": "8806094215039"}
    )
    version = await _match(db, observation)
    assert version is not None
    assert version.state == "proposed"


async def test_llm_proposed_match_is_not_auto_confirmed(db: Database) -> None:
    offer, _ = await _setup(db, mpn="MZ-V9P1T0BW")
    observation = await _observe(
        db, offer, title="SSD سامسونگ 990 PRO 1TB", identifiers={"mpn": "MZ-V9P1T0BW"}
    )
    async with db.tenant_session(TENANT_A) as session:
        await record_attributes(session, TENANT_A, observation)
        version = await evaluate(
            session, TENANT_A, MarketOffer(offer, "لیون"), proposed_by=DecisionSource.LLM
        )
    assert version is not None
    assert (version.state, version.decided_by) == ("proposed", "llm")


async def test_expert_rejects_match_and_pair_is_not_reproposed(db: Database) -> None:
    offer, _ = await _setup(db)
    observation = await _observe(db, offer, title="SSD سامسونگ 990 PRO 1TB")
    proposed = await _match(db, observation)
    assert proposed is not None
    async with db.tenant_session(TENANT_A) as session:
        with pytest.raises(ValidationFailed):
            await decide(
                session,
                tenant_id=TENANT_A,
                actor=ADMIN,
                match_version_id=proposed.id,
                action=ExpertAction.REJECT,
                reason=" ",
            )
    async with db.tenant_session(TENANT_A) as session:
        rejected = await decide(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            match_version_id=proposed.id,
            action=ExpertAction.REJECT,
            reason="نسل متفاوت",
        )
    async with db.tenant_session(TENANT_A) as session:
        again = await evaluate(session, TENANT_A, MarketOffer(offer, "لیون"))
        versions = await history(session, MarketOffer(offer, "لیون"))
        audit = await list_events(session, action="match.reject")
    assert rejected.state == "rejected"
    assert again is None  # unchanged attributes: not proposed again
    assert [(v.state, v.is_current) for v in versions] == [("proposed", False), ("rejected", True)]
    assert rejected.previous_version_id == proposed.id
    assert audit[0].reason == "نسل متفاوت"
    assert audit[0].before == {
        "state": "proposed",
        "variant_id": str(proposed.variant_id),
        "flags": [],
    }

    changed = await _observe(db, offer, title="SSD سامسونگ 990 PRO 2TB")  # attributes change
    async with db.tenant_session(TENANT_A) as session:
        await record_attributes(session, TENANT_A, changed)
        reproposed = await evaluate(session, TENANT_A, MarketOffer(offer, "لیون"))
    assert reproposed is not None


async def test_condition_mismatch_needs_review_and_equivalence_needs_reason(db: Database) -> None:
    offer, _ = await _setup(
        db,
        brand="ASUS",
        model="RTX 4060",
        category="gpu",
        attributes={"capacity": "8GB", "warranty_provider": "آواژنگ", "warranty_months": 36},
    )
    observation = await _observe(
        db, offer, title="کارت گرافیک ایسوس RTX 4060 8GB", warranty="گارانتی ۱۸ ماهه سازگار ارقام"
    )
    version = await _match(db, observation)
    assert version is not None
    assert version.state == "needs_review"
    assert "condition_mismatch:warranty" in version.flags
    async with db.tenant_session(TENANT_A) as session:
        with pytest.raises(ValidationFailed, match="reason"):
            await decide(
                session,
                tenant_id=TENANT_A,
                actor=ADMIN,
                match_version_id=version.id,
                action=ExpertAction.CONFIRM,
                reason=None,
            )
    async with db.tenant_session(TENANT_A) as session:
        confirmed = await decide(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            match_version_id=version.id,
            action=ExpertAction.CONFIRM,
            reason="گارانتی معادل در عمل",
        )
    assert (confirmed.state, confirmed.decided_by) == ("confirmed", "human")


async def test_confirmed_match_reassigned_keeps_history(db: Database) -> None:
    offer, v1 = await _setup(db)
    v2 = await seed_variant(db, TENANT_A, sku="SSD-2", attributes={"capacity": "2TB"})
    observation = await _observe(db, offer, title="SSD سامسونگ 990 PRO 1TB")
    proposed = await _match(db, observation)
    assert proposed is not None
    async with db.tenant_session(TENANT_A) as session:
        confirmed = await decide(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            match_version_id=proposed.id,
            action=ExpertAction.CONFIRM,
            reason=None,
        )
    async with db.tenant_session(TENANT_A) as session:
        moved = await decide(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            match_version_id=confirmed.id,
            action=ExpertAction.REASSIGN,
            reason="ظرفیت ۲ ترابایت است",
            target_variant_id=v2,
        )
    async with db.tenant_session(TENANT_A) as session:
        with pytest.raises(Conflict):
            await decide(
                session,
                tenant_id=TENANT_A,
                actor=ADMIN,
                match_version_id=confirmed.id,
                action=ExpertAction.CONFIRM,
                reason=None,
            )
        versions = await history(session, MarketOffer(offer, "لیون"))
        current = await current_match(session, MarketOffer(offer, "لیون"))
    assert current is not None
    assert (current.id, current.variant_id) == (moved.id, v2)
    assert [(v.variant_id, v.is_current) for v in versions] == [
        (v1, False),
        (v1, False),
        (v2, True),
    ]


async def test_new_observation_flows_to_proposed_match_through_consumers(db: Database) -> None:
    offer, _ = await _setup(db)
    observation = await _observe(db, offer, title="SSD سامسونگ 990 PRO 1TB")
    async with db.tenant_session(TENANT_A) as session:
        await publish(
            session,
            tenant_id=TENANT_A,
            event=ObservationRecorded(
                observation_ids=[observation.id],
                tracked_offer_id=offer,
                variant_id=observation.variant_id,
                source_id=observation.source_id,
                is_own_store=False,
                is_own_channel=False,
            ),
        )
    for event_type, handler in (
        ("observation.recorded", on_observation_recorded),
        ("offer.attributes.updated", on_attributes_updated),
    ):
        async with db.tenant_session(TENANT_A) as session:
            rows = (
                await session.scalars(
                    select(OutboxEventRow).where(OutboxEventRow.type == event_type)
                )
            ).all()
        for row in rows:
            await consume(db, f"test.{event_type}", row.envelope(), handler)
    async with db.tenant_session(TENANT_A) as session:
        match = await current_match(session, MarketOffer(offer, "لیون"))
        types = (await session.scalars(select(OutboxEventRow.type))).all()
    assert match is not None
    assert match.state == "proposed"
    assert "match.changed" in types
