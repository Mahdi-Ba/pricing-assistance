"""Queue item detail: recommendation, explanation and evidence rows (task 11.4).

Evidence rows are the offers behind the *stored* recommendation, evaluated as of its time with
its rule versions, so each row's "why it did not qualify" matches what the engine did. Age and
freshness are shown as of now. Evidence snapshots are linked with short-lived presigned URLs.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.collection.api import Freshness, ObservationRow, classify
from pricing_assistant.core.errors import NotFound
from pricing_assistant.decisions.api import DecisionRow, DecisionView, decision_views
from pricing_assistant.matching.api import MatchVersionRow
from pricing_assistant.pricing.api import Disqualification, recommendation_evidence
from pricing_assistant.sources.api import SourceRow, TrackedOfferRow
from pricing_assistant.workspace.queue import QueueItem, load_queue

DISQUALIFICATION_FA = {
    Disqualification.MATCH_PENDING: "تطبیق هنوز تأیید نشده است",
    Disqualification.MATCH_NOT_CONFIRMED: "تطبیق تأیید نشده است",
    Disqualification.CONDITION_MISMATCH: "شرایط فروش (گارانتی، وضعیت یا پرداخت) متفاوت است",
    Disqualification.OUT_OF_STOCK: "ناموجود",
    Disqualification.INVALID_PRICE: "قیمت نامعتبر یا نامشخص",
    Disqualification.SOURCE_NOT_APPROVED: "منبع هنوز تأیید نشده است",
    Disqualification.OUTSIDE_COMPETITOR_SET: "خارج از مجموعه رقبای تعیین‌شده",
    Disqualification.STALE: "قیمت قدیمی است",
    Disqualification.PRICE_OUTLIER: "قیمت پرت؛ تا تأیید کارشناس لحاظ نمی‌شود",
}
ROW_FLAGS = (
    Disqualification.CONDITION_MISMATCH,
    Disqualification.PRICE_OUTLIER,
    Disqualification.OUTSIDE_COMPETITOR_SET,
)


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    id: uuid.UUID
    kind: str
    url: str | None  # None once retention removed the snapshot


Presign = Callable[[uuid.UUID], Awaitable[EvidenceLink]]


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    observation_id: uuid.UUID
    tracked_offer_id: uuid.UUID
    source_id: uuid.UUID
    source_name: str
    url: str
    seller: str | None
    title: str | None
    price_rial: int | None
    stock_state: str
    conditions: dict[str, object]
    observed_at: datetime
    age_seconds: int
    freshness: Freshness
    match_version_id: uuid.UUID
    match_state: str
    match_flags: list[str]
    flags: list[str]
    qualifies: bool
    is_market_reference: bool
    reasons: list[Disqualification]
    reasons_fa: list[str]
    evidence: list[EvidenceLink]


@dataclass(frozen=True, slots=True)
class ItemDetail:
    item: QueueItem
    rows: list[EvidenceRow]
    inputs_purged: bool
    decision: DecisionView | None


async def item_detail(
    session: AsyncSession,
    variant_id: uuid.UUID,
    presign: Presign,
    *,
    now: datetime | None = None,
) -> ItemDetail:
    now = now or datetime.now(UTC)
    items = await load_queue(session, now=now, variant_ids={variant_id})
    if not items:
        raise NotFound(
            "No recommendation for this variant", message_fa="برای این کالا پیشنهادی وجود ندارد."
        )
    item = items[0]
    rec = item.recommendation
    evidence = await recommendation_evidence(session, rec)
    decision = None
    if item.decision_id is not None:
        row = await session.get(DecisionRow, item.decision_id)
        if row is not None:
            decision = (await decision_views(session, [row]))[row.id]
    if evidence is None:
        return ItemDetail(item=item, rows=[], inputs_purged=True, decision=decision)

    ids = [e.offer.observation_id for e in evidence.offers]
    observations = {
        o.id: o
        for o in (await session.scalars(select(ObservationRow).where(ObservationRow.id.in_(ids))))
    }
    match_ids = [e.offer.match_version_id for e in evidence.offers]
    matches = {
        m.id: m
        for m in (
            await session.scalars(select(MatchVersionRow).where(MatchVersionRow.id.in_(match_ids)))
        )
    }
    sources = {
        s.id: s
        for s in (
            await session.scalars(
                select(SourceRow).where(
                    SourceRow.id.in_({e.offer.source_id for e in evidence.offers})
                )
            )
        )
    }
    max_age = (
        evidence.rule.max_data_age_seconds[item.variant.importance_tier]
        if evidence.rule is not None
        else None
    )
    rows: list[EvidenceRow] = []
    for entry in sorted(
        evidence.offers, key=lambda e: (e.offer.price_rial or 0, str(e.offer.observation_id))
    ):
        obs = observations[entry.offer.observation_id]
        match = matches[entry.offer.match_version_id]
        source = sources.get(obs.source_id)
        tracked = await session.get(TrackedOfferRow, obs.tracked_offer_id)
        rows.append(
            EvidenceRow(
                observation_id=obs.id,
                tracked_offer_id=obs.tracked_offer_id,
                source_id=obs.source_id,
                source_name=source.name if source else "",
                url=tracked.url if tracked else obs.url,
                seller=obs.seller,
                title=obs.title,
                price_rial=obs.price_rial,
                stock_state=obs.stock_state,
                conditions=dict(obs.conditions or {}),
                observed_at=obs.observed_at,
                age_seconds=int((now - obs.observed_at).total_seconds()),
                freshness=classify(
                    last_observed_at=obs.observed_at,
                    last_failure_at=None,
                    max_age_seconds=max_age,
                    now=now,
                )
                if max_age is not None
                else Freshness.FRESH,
                match_version_id=match.id,
                match_state=match.state,
                match_flags=list(match.flags),
                flags=[d.value for d in entry.disqualifications if d in ROW_FLAGS],
                qualifies=not entry.disqualifications,
                is_market_reference=obs.id == rec.market_ref_observation_id,
                reasons=entry.disqualifications,
                reasons_fa=[DISQUALIFICATION_FA[d] for d in entry.disqualifications],
                evidence=[await presign(evidence_id) for evidence_id in obs.evidence_ids],
            )
        )
    return ItemDetail(item=item, rows=rows, inputs_purged=False, decision=decision)
