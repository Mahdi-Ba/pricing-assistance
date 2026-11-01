"""Monthly match audit (task 13.1, Q-K2).

The population is every match confirmed during the month that is still the current version
(an expert later correcting it removes it from the population). Each match is stratified by
its variant's category, its source and the confidence band of the proposal it was confirmed
from. An admin marks each sampled match correct or incorrect once; accuracy is correct ÷
reviewed, overall and per stratum, against the ≥98% target. Incorrect matches are listed for
correction.
"""

import secrets
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.catalog.api import list_variants
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.ids import new_id
from pricing_assistant.matching.api import DecisionSource, MatchState, MatchVersionRow
from pricing_assistant.reporting.models import MatchAuditItemRow, MatchAuditSampleRow
from pricing_assistant.reporting.sampling import (
    DEFAULT_SAMPLE_SIZE,
    Candidate,
    confidence_band,
    share,
    stratified_sample,
)
from pricing_assistant.sources.api import TrackedOfferRow

ACCURACY_TARGET_PCT = 98.0
DECEMBER = 12


def month_bounds(period: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(f"{period}-01", "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValidationFailed(
            "Period must be YYYY-MM", message_fa="دوره باید به شکل YYYY-MM باشد."
        ) from exc
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == DECEMBER
        else start.replace(month=start.month + 1)
    )
    return start, end


async def population(session: AsyncSession, period: str) -> list[Candidate]:
    start, end = month_bounds(period)
    confirmed = (
        await session.scalars(
            select(MatchVersionRow).where(
                MatchVersionRow.is_current.is_(True),
                MatchVersionRow.state == MatchState.CONFIRMED.value,
                MatchVersionRow.created_at >= start,
                MatchVersionRow.created_at < end,
            )
        )
    ).all()
    if not confirmed:
        return []
    previous_ids = [m.previous_version_id for m in confirmed if m.previous_version_id]
    proposals = (
        {
            p.id: p
            for p in (
                await session.scalars(
                    select(MatchVersionRow).where(MatchVersionRow.id.in_(previous_ids))
                )
            ).all()
        }
        if previous_ids
        else {}
    )
    offers = {
        o.id: o.source_id
        for o in (
            await session.scalars(
                select(TrackedOfferRow).where(
                    TrackedOfferRow.id.in_({m.tracked_offer_id for m in confirmed})
                )
            )
        ).all()
    }
    categories = {v.id: v.category for v in await list_variants(session)}
    candidates = []
    for match in confirmed:
        exact = match.decided_by == DecisionSource.RULE.value
        proposal = proposals.get(match.previous_version_id) if match.previous_version_id else None
        proposed_confidence = (
            proposal.confidence_bp if proposal is not None else match.confidence_bp
        )
        candidates.append(
            Candidate(
                match_version_id=match.id,
                category=categories.get(match.variant_id, "unknown"),
                source_id=offers[match.tracked_offer_id],
                band=confidence_band(proposed_confidence, exact=exact),
            )
        )
    return candidates


async def draw_sample(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    period: str,
    size: int = DEFAULT_SAMPLE_SIZE,
) -> MatchAuditSampleRow:
    if size < 1:
        raise ValidationFailed(
            "Sample size must be positive", message_fa="اندازه نمونه باید مثبت باشد."
        )
    candidates = await population(session, period)
    seed = secrets.randbits(62)
    chosen = stratified_sample(candidates, size=size, seed=seed)
    sample = MatchAuditSampleRow(
        id=new_id(),
        tenant_id=tenant_id,
        period=period,
        population=len(candidates),
        size=len(chosen),
        seed=seed,
        created_by=actor.username,
    )
    session.add(sample)
    await session.flush()
    session.add_all(
        MatchAuditItemRow(
            id=new_id(),
            tenant_id=tenant_id,
            sample_id=sample.id,
            match_version_id=c.match_version_id,
            category=c.category,
            source_id=c.source_id,
            confidence_band=c.band,
        )
        for c in chosen
    )
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="report.match_audit.drawn",
        target_type="match_audit_sample",
        target_id=sample.id,
        after={"period": period, "population": len(candidates), "size": len(chosen), "seed": seed},
    )
    return sample


async def record_verdict(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    item_id: uuid.UUID,
    correct: bool,
    note: str | None,
) -> MatchAuditItemRow:
    item = await session.get(MatchAuditItemRow, item_id, with_for_update=True)
    if item is None:
        raise NotFound("Audit item not found", message_fa="مورد نمونه یافت نشد.")
    if item.verdict is not None:
        raise Conflict(
            "This match was already audited",
            code="already_audited",
            message_fa="این تطبیق قبلاً بررسی شده است.",
        )
    note = (note or "").strip() or None
    if not correct and note is None:
        raise ValidationFailed(
            "Say what is wrong with an incorrect match",
            code="note_required",
            message_fa="برای تطبیق نادرست، دلیل را بنویسید.",
        )
    item.verdict = "correct" if correct else "incorrect"
    item.note = note
    item.reviewed_by = actor.username
    item.reviewed_at = datetime.now(UTC)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="report.match_audit.verdict",
        target_type="match_version",
        target_id=item.match_version_id,
        after={"verdict": item.verdict, "sample_id": str(item.sample_id)},
        reason=note,
    )
    return item


@dataclass(frozen=True, slots=True)
class Accuracy:
    reviewed: int
    correct: int
    accuracy_pct: float | None


@dataclass(frozen=True, slots=True)
class AuditResult:
    sample: MatchAuditSampleRow
    items: list[MatchAuditItemRow]
    overall: Accuracy
    by_category: dict[str, Accuracy] = field(default_factory=dict)
    by_source: dict[str, Accuracy] = field(default_factory=dict)
    by_band: dict[str, Accuracy] = field(default_factory=dict)
    incorrect: list[MatchAuditItemRow] = field(default_factory=list)
    target_pct: float = ACCURACY_TARGET_PCT


def _accuracy(items: list[MatchAuditItemRow]) -> Accuracy:
    reviewed = [i for i in items if i.verdict is not None]
    correct = sum(1 for i in reviewed if i.verdict == "correct")
    return Accuracy(
        reviewed=len(reviewed), correct=correct, accuracy_pct=share(correct, len(reviewed))
    )


def _grouped(items: list[MatchAuditItemRow], key: str) -> dict[str, Accuracy]:
    groups: dict[str, list[MatchAuditItemRow]] = defaultdict(list)
    for item in items:
        groups[str(getattr(item, key))].append(item)
    return {k: _accuracy(v) for k, v in sorted(groups.items())}


async def audit_result(session: AsyncSession, sample_id: uuid.UUID) -> AuditResult:
    sample = await session.get(MatchAuditSampleRow, sample_id)
    if sample is None:
        raise NotFound("Audit sample not found", message_fa="نمونه بررسی یافت نشد.")
    items = list(
        (
            await session.scalars(
                select(MatchAuditItemRow)
                .where(MatchAuditItemRow.sample_id == sample_id)
                .order_by(MatchAuditItemRow.category, MatchAuditItemRow.id)
            )
        ).all()
    )
    return AuditResult(
        sample=sample,
        items=items,
        overall=_accuracy(items),
        by_category=_grouped(items, "category"),
        by_source=_grouped(items, "source_id"),
        by_band=_grouped(items, "confidence_band"),
        incorrect=[i for i in items if i.verdict == "incorrect"],
    )


async def latest_sample(
    session: AsyncSession, period: str | None = None
) -> MatchAuditSampleRow | None:
    query = select(MatchAuditSampleRow).order_by(MatchAuditSampleRow.created_at.desc()).limit(1)
    if period is not None:
        query = query.where(MatchAuditSampleRow.period == period)
    row: MatchAuditSampleRow | None = await session.scalar(query)
    return row
