"""Fetch execution in the collection workers (tasks 5.3, 5.4, 5.6).

For one fetch request:

1. Claim the (offer, window) so a duplicate request executes nothing.
2. Run the connector through the runtime gate (clearance, quota) — outside any transaction.
3. Record the attempt. On success store evidence and one observation per seller offer; on
   failure record the failure only. A failure never becomes an out-of-stock observation.
4. Retry transient failures with exponential backoff and jitter, at most three attempts. Quota
   or pause refusals are deferred (delayed, not dropped) without counting as attempts.
"""

import random
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.collection.events import FetchFailed, FetchRequested, ObservationRecorded
from pricing_assistant.collection.evidence import register
from pricing_assistant.collection.metrics import FETCH_OUTCOMES, OBSERVATIONS
from pricing_assistant.collection.models import (
    FetchAttemptRow,
    FetchClaimRow,
    FetchOutcome,
    ObservationRow,
    RecheckRequestRow,
    RecheckStatus,
    Validity,
)
from pricing_assistant.collection.runtime import CollectionRuntime
from pricing_assistant.core.correlation import get_correlation_id
from pricing_assistant.core.events import EventEnvelope, publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.logging import get_logger
from pricing_assistant.sources.api import (
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    ObservationDraft,
    ObservedOffer,
    TrackedOfferRow,
    prepare_fetch,
    run_fetch,
)

MAX_ATTEMPTS = 3
MAX_DEFERRALS = 20
BACKOFF_BASE_MS = 30_000
SUSPECT_LOW, SUSPECT_HIGH = 0.2, 5.0
log = get_logger(__name__)


def backoff_ms(attempt: int, *, rng: random.Random | None = None) -> int:
    """Exponential backoff with full jitter: base·2^(attempt−1) plus up to one base."""
    jitter = (rng or random.SystemRandom()).randint(0, BACKOFF_BASE_MS)
    return (BACKOFF_BASE_MS << (attempt - 1)) + jitter


async def _claim(session: AsyncSession, request: FetchRequested, tenant_id: uuid.UUID) -> bool:
    claimed = await session.scalar(
        insert(FetchClaimRow)
        .values(
            tracked_offer_id=request.tracked_offer_id,
            window_start=request.window_start,
            tenant_id=tenant_id,
            trigger=request.trigger,
        )
        .on_conflict_do_nothing()
        .returning(FetchClaimRow.tracked_offer_id)
    )
    return claimed is not None


async def _last_valid_price(
    session: AsyncSession, tracked_offer_id: uuid.UUID, seller: str | None
) -> int | None:
    query = (
        select(ObservationRow.price_rial)
        .where(
            ObservationRow.tracked_offer_id == tracked_offer_id,
            ObservationRow.validity == Validity.VALID.value,
            ObservationRow.price_rial.is_not(None),
        )
        .order_by(ObservationRow.observed_at.desc())
        .limit(1)
    )
    query = query.where(
        ObservationRow.seller.is_(None) if seller is None else ObservationRow.seller == seller
    )
    price: int | None = await session.scalar(query)
    return price


def plausibility(price: int | None, previous: int | None) -> Validity:
    """``suspect_unit`` when a price jumps outside 0.2×–5× of the last valid one (Rial/Toman)."""
    if price is None or previous is None or previous <= 0:
        return Validity.VALID
    ratio = price / previous
    return Validity.VALID if SUSPECT_LOW <= ratio <= SUSPECT_HIGH else Validity.SUSPECT_UNIT


def _conditions(offer: ObservedOffer) -> dict[str, Any]:
    return {
        key: value
        for key, value in (
            ("warranty", offer.conditions.warranty),
            ("condition", offer.conditions.condition),
            ("payment", offer.conditions.payment),
        )
        if value
    }


async def _record_success(
    rt: CollectionRuntime,
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    attempt: FetchAttemptRow,
    draft: ObservationDraft,
) -> list[uuid.UUID]:
    target = draft.target
    stored = await rt.evidence().store(
        tenant_id=tenant_id,
        source_id=target.source_id,
        tracked_offer_id=target.tracked_offer_id,
        observed_at=draft.observed_at,
        evidence=draft.evidence,
    )
    evidence_rows = await register(
        session,
        tenant_id=tenant_id,
        source_id=target.source_id,
        tracked_offer_id=target.tracked_offer_id,
        observed_at=draft.observed_at,
        objects=stored,
    )
    ids: list[uuid.UUID] = []
    for offer in draft.offers:
        validity = plausibility(
            offer.price_rial,
            await _last_valid_price(session, target.tracked_offer_id, offer.seller),
        )
        observation = ObservationRow(
            id=new_id(),
            tenant_id=tenant_id,
            tracked_offer_id=target.tracked_offer_id,
            source_id=target.source_id,
            variant_id=target.variant_id,
            fetch_attempt_id=attempt.id,
            observed_at=draft.observed_at,
            url=target.url,
            method=draft.method.value,
            seller=offer.seller,
            title=offer.title,
            price_rial=offer.price_rial,
            stock_state=offer.stock.value,
            conditions=_conditions(offer),
            identifiers=dict(offer.identifiers),
            validity=validity.value,
            is_own_store=target.is_own_store,
            is_own_channel=target.is_own_channel,
            extraction_rule_version_id=draft.extraction_rule_version_id,
            evidence_ids=[row.id for row in evidence_rows],
        )
        session.add(observation)
        ids.append(observation.id)
        OBSERVATIONS.labels(validity.value).inc()
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=ObservationRecorded(
            observation_ids=ids,
            tracked_offer_id=target.tracked_offer_id,
            variant_id=target.variant_id,
            source_id=target.source_id,
            is_own_store=target.is_own_store,
            is_own_channel=target.is_own_channel,
        ),
    )
    return ids


async def _finish_recheck(
    session: AsyncSession, request: FetchRequested, attempt: FetchAttemptRow
) -> None:
    if request.recheck_id is None or not attempt.final:
        return
    recheck = await session.get(RecheckRequestRow, request.recheck_id, with_for_update=True)
    if recheck is not None and recheck.status == RecheckStatus.PENDING.value:
        recheck.status = (
            RecheckStatus.COMPLETED
            if attempt.outcome == FetchOutcome.SUCCESS.value
            else RecheckStatus.FAILED
        ).value
        recheck.fetch_attempt_id = attempt.id
        recheck.completed_at = datetime.now(UTC)


async def _persist(
    rt: CollectionRuntime,
    tenant_id: uuid.UUID,
    request: FetchRequested,
    offer: TrackedOfferRow,
    result: FetchResult,
) -> FetchAttemptRow:
    failure = result if isinstance(result, FetchFailure) else None
    final = failure is None or not failure.retryable or request.attempt >= MAX_ATTEMPTS
    async with rt.database().tenant_session(tenant_id) as session:
        attempt = FetchAttemptRow(
            id=new_id(),
            tenant_id=tenant_id,
            tracked_offer_id=offer.id,
            source_id=offer.source_id,
            window_start=request.window_start,
            attempt=request.attempt,
            trigger=request.trigger,
            outcome=(FetchOutcome.FAILURE if failure else FetchOutcome.SUCCESS).value,
            error_class=failure.error_class.value if failure else None,
            detail=failure.detail[:500] if failure else None,
            http_status=result.http_status,
            latency_ms=result.latency_ms,
            offers_count=len(result.offers) if isinstance(result, ObservationDraft) else 0,
            final=final,
            correlation_id=get_correlation_id(),
        )
        session.add(attempt)
        await session.flush()
        if isinstance(result, ObservationDraft):
            await _record_success(rt, session, tenant_id=tenant_id, attempt=attempt, draft=result)
        else:
            await publish(
                session,
                tenant_id=tenant_id,
                event=FetchFailed(
                    tracked_offer_id=offer.id,
                    variant_id=offer.variant_id,
                    source_id=offer.source_id,
                    error_class=result.error_class.value,
                    final=final,
                ),
            )
        await _finish_recheck(session, request, attempt)
    FETCH_OUTCOMES.labels(
        str(offer.source_id), attempt.outcome, attempt.error_class or "none"
    ).inc()
    return attempt


def _follow_up(
    envelope: EventEnvelope, request: FetchRequested, **changes: object
) -> EventEnvelope:
    payload = request.model_copy(update=changes).model_dump(mode="json")
    return envelope.model_copy(
        update={"event_id": new_id(), "causation_id": envelope.event_id, "payload": payload}
    )


async def handle_fetch(rt: CollectionRuntime, envelope: EventEnvelope) -> FetchAttemptRow | None:
    """Raw consumer for ``fetch.requested`` and ``fetch.requested.browser``."""
    request = FetchRequested.model_validate(envelope.payload)
    tenant_id = envelope.tenant_id
    db = rt.database()
    async with db.tenant_session(tenant_id) as session:
        if (
            request.attempt == 1
            and request.deferrals == 0
            and not await _claim(session, request, tenant_id)
        ):
            log.info(
                "collection.duplicate_window_skipped",
                tracked_offer_id=str(request.tracked_offer_id),
                window_start=request.window_start.isoformat(),
            )
            return None
        offer = await session.get(TrackedOfferRow, request.tracked_offer_id)
        if offer is None:
            return None
        prepared = await prepare_fetch(
            session,
            tenant_id=tenant_id,
            tracked_offer_id=offer.id,
            box=rt.box,
            user_agent=rt.settings.collector_user_agent,
            timeout_seconds=rt.settings.collector_timeout_seconds,
        )
    result = await run_fetch(
        prepared,
        limiter=rt.limiter(),
        connectors=rt.connectors(),
        slot_reserved=request.slot_reserved,
    )
    if (
        isinstance(result, FetchFailure)
        and result.error_class is FetchErrorClass.QUOTA_EXHAUSTED
        and request.deferrals < MAX_DEFERRALS
    ):
        delay = (result.retry_after_seconds or 1) * 1000
        rt.requeue(_follow_up(envelope, request, deferrals=request.deferrals + 1), delay)
        return None
    attempt = await _persist(rt, tenant_id, request, offer, result)
    if not attempt.final:
        rt.requeue(
            _follow_up(envelope, request, attempt=request.attempt + 1, slot_reserved=False),
            backoff_ms(request.attempt),
        )
    return attempt
