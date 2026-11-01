"""Pilot KPIs: floor safety, evidence completeness, review time (tasks 13.2, 13.3).

Every figure is computed from recorded rows for the period ``[start, end)`` and returned with
its sample size and the target it is measured against. Targets are the PRD pilot goals.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.catalog.api import list_variants
from pricing_assistant.collection.api import ObservationRow, Validity
from pricing_assistant.core.errors import ValidationFailed
from pricing_assistant.core.ids import new_id
from pricing_assistant.decisions.api import DecisionRow, OverrideReviewRow, Verdict
from pricing_assistant.pricing.api import Outcome, RecommendationRow
from pricing_assistant.reporting.models import ReviewBaselineRow
from pricing_assistant.reporting.sampling import median, percentile, share
from pricing_assistant.workspace.api import ReviewSessionRow

LOW_SAMPLE = 30
REVIEW_REDUCTION_TARGET_PCT = 50.0
EVIDENCE_TARGET_PCT = 100.0
FLOOR_SAFETY_TARGET = 0
SAME_REVIEW_SLACK = timedelta(minutes=1)


# --- 13.2 floor safety ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OverrideEntry:
    decision_id: uuid.UUID
    variant_id: uuid.UUID
    applied_price_rial: int | None
    floor_rial: int | None
    requested_by: str
    request_reason: str | None
    verdict: str | None  # approved | rejected | self_approved | None (pending)
    approver: str | None
    review_reason: str | None
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class FloorSafety:
    recommendations: int
    below_floor_suggestions: int
    below_floor_ids: list[uuid.UUID]
    overrides: list[OverrideEntry]
    self_approved: int
    target: int = FLOOR_SAFETY_TARGET


async def floor_safety(session: AsyncSession, start: datetime, end: datetime) -> FloorSafety:
    recs = (
        await session.execute(
            select(
                RecommendationRow.id,
                RecommendationRow.suggested_price_rial,
                RecommendationRow.floor_rial,
            ).where(RecommendationRow.created_at >= start, RecommendationRow.created_at < end)
        )
    ).all()
    below = [
        rec_id
        for rec_id, suggested, floor in recs
        if suggested is not None and floor is not None and suggested < floor
    ]
    decisions = (
        await session.scalars(
            select(DecisionRow)
            .where(
                DecisionRow.below_floor_override.is_(True),
                DecisionRow.created_at >= start,
                DecisionRow.created_at < end,
            )
            .order_by(DecisionRow.created_at)
        )
    ).all()
    reviews = (
        {
            r.decision_id: r
            for r in (
                await session.scalars(
                    select(OverrideReviewRow).where(
                        OverrideReviewRow.decision_id.in_([d.id for d in decisions])
                    )
                )
            ).all()
        }
        if decisions
        else {}
    )
    overrides = [
        OverrideEntry(
            decision_id=d.id,
            variant_id=d.variant_id,
            applied_price_rial=d.applied_price_rial,
            floor_rial=d.floor_rial,
            requested_by=d.actor,
            request_reason=d.override_reason,
            verdict=reviews[d.id].verdict if d.id in reviews else None,
            approver=reviews[d.id].actor if d.id in reviews else None,
            review_reason=reviews[d.id].reason if d.id in reviews else None,
            decided_at=d.created_at,
        )
        for d in decisions
    ]
    return FloorSafety(
        recommendations=len(recs),
        below_floor_suggestions=len(below),
        below_floor_ids=below,
        overrides=overrides,
        self_approved=sum(1 for o in overrides if o.verdict == Verdict.SELF_APPROVED.value),
    )


# --- 13.2 evidence completeness -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceCompleteness:
    actionable: int
    complete: int
    completeness_pct: float | None
    non_compliant_ids: list[uuid.UUID]
    target_pct: float = EVIDENCE_TARGET_PCT


async def evidence_completeness(
    session: AsyncSession, start: datetime, end: datetime
) -> EvidenceCompleteness:
    """Actionable recommendations referencing ≥1 valid observation with source and time."""
    recs = (
        await session.execute(
            select(RecommendationRow.id, RecommendationRow.qualifying_observation_ids).where(
                RecommendationRow.created_at >= start,
                RecommendationRow.created_at < end,
                RecommendationRow.outcome.in_([Outcome.INCREASE.value, Outcome.DECREASE.value]),
            )
        )
    ).all()
    referenced = {obs_id for _, ids in recs for obs_id in ids}
    valid = (
        set(
            (
                await session.scalars(
                    select(ObservationRow.id).where(
                        ObservationRow.id.in_(referenced),
                        ObservationRow.validity == Validity.VALID.value,
                        ObservationRow.source_id.is_not(None),
                        ObservationRow.observed_at.is_not(None),
                    )
                )
            ).all()
        )
        if referenced
        else set()
    )
    bad = [rec_id for rec_id, ids in recs if not set(ids) & valid]
    complete = len(recs) - len(bad)
    return EvidenceCompleteness(
        actionable=len(recs),
        complete=complete,
        completeness_pct=share(complete, len(recs)),
        non_compliant_ids=bad,
    )


# --- 13.3 review time -----------------------------------------------------------------------------


async def set_baseline(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    category: str,
    median_minutes: float,
    note: str | None,
) -> ReviewBaselineRow:
    if not category.strip() or median_minutes <= 0:
        raise ValidationFailed(
            "A category and a positive median are required",
            message_fa="دسته و میانه زمان (بیشتر از صفر) را وارد کنید.",
        )
    row = ReviewBaselineRow(
        id=new_id(),
        tenant_id=tenant_id,
        category=category.strip(),
        median_seconds=round(median_minutes * 60),
        note=(note or "").strip() or None,
        entered_by=actor.username,
    )
    session.add(row)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="report.baseline.set",
        target_type="review_baseline",
        target_id=row.id,
        after={"category": row.category, "median_seconds": row.median_seconds},
        reason=row.note,
    )
    return row


async def baselines(session: AsyncSession) -> dict[str, ReviewBaselineRow]:
    """The latest baseline per category."""
    rows = (
        await session.scalars(select(ReviewBaselineRow).order_by(ReviewBaselineRow.created_at))
    ).all()
    return {r.category: r for r in rows}


@dataclass(frozen=True, slots=True)
class CategoryReviewTime:
    category: str
    decisions: int
    median_seconds: float | None
    p90_seconds: float | None
    baseline_seconds: int | None
    low_sample: bool


@dataclass(frozen=True, slots=True)
class ReviewTime:
    decisions: int
    median_seconds: float | None
    p90_seconds: float | None
    low_sample: bool
    categories: list[CategoryReviewTime]
    weighted_baseline_seconds: float | None
    weighted_measured_seconds: float | None
    reduction_pct: float | None
    categories_without_baseline: list[str] = field(default_factory=list)
    target_pct: float = REVIEW_REDUCTION_TARGET_PCT


def weighted_reduction(
    per_category: list[CategoryReviewTime],
) -> tuple[float | None, float | None, float | None]:
    """Baseline and measured medians weighted by the pilot's decision count per category."""
    usable = [
        c for c in per_category if c.baseline_seconds is not None and c.median_seconds is not None
    ]
    weight = sum(c.decisions for c in usable)
    if not weight:
        return None, None, None
    baseline = sum(c.decisions * (c.baseline_seconds or 0) for c in usable) / weight
    measured = sum(c.decisions * (c.median_seconds or 0) for c in usable) / weight
    return baseline, measured, round(100 * (1 - measured / baseline), 2)


async def _review_seconds(
    session: AsyncSession, decisions: list[DecisionRow]
) -> dict[uuid.UUID, float]:
    """Per decision: the summed time of its actor's sessions on the item before deciding."""
    if not decisions:
        return {}
    variant_ids = {d.variant_id for d in decisions}
    sessions = (
        await session.scalars(
            select(ReviewSessionRow).where(
                ReviewSessionRow.variant_id.in_(variant_ids),
                ReviewSessionRow.closed_at.is_not(None),
            )
        )
    ).all()
    earlier = (
        await session.execute(
            select(DecisionRow.variant_id, DecisionRow.created_at).where(
                DecisionRow.variant_id.in_(variant_ids)
            )
        )
    ).all()
    previous: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    for variant_id, created in earlier:
        previous[variant_id].append(created)
    result: dict[uuid.UUID, float] = {}
    for decision in decisions:
        since = max(
            (t for t in previous[decision.variant_id] if t < decision.created_at), default=None
        )
        spent = [
            (s.closed_at - s.opened_at).total_seconds()
            for s in sessions
            if s.closed_at is not None
            and s.variant_id == decision.variant_id
            and s.user_subject == decision.actor_subject
            and (
                s.decision_id == decision.id
                or (
                    s.closed_at <= decision.created_at + SAME_REVIEW_SLACK
                    and (since is None or s.opened_at >= since)
                )
            )
        ]
        if spent:
            result[decision.id] = sum(spent)
    return result


async def review_time(session: AsyncSession, start: datetime, end: datetime) -> ReviewTime:
    decisions = list(
        (
            await session.scalars(
                select(DecisionRow).where(
                    DecisionRow.created_at >= start,
                    DecisionRow.created_at < end,
                    DecisionRow.supersedes_decision_id.is_(None),  # corrections are not reviews
                )
            )
        ).all()
    )
    seconds = await _review_seconds(session, decisions)
    categories = {v.id: v.category for v in await list_variants(session)}
    by_category: dict[str, list[float]] = defaultdict(list)
    for decision in decisions:
        if decision.id in seconds:
            by_category[categories.get(decision.variant_id, "unknown")].append(seconds[decision.id])
    known = await baselines(session)
    per_category = [
        CategoryReviewTime(
            category=category,
            decisions=len(values),
            median_seconds=median(values),
            p90_seconds=percentile(values, 90),
            baseline_seconds=known[category].median_seconds if category in known else None,
            low_sample=len(values) < LOW_SAMPLE,
        )
        for category, values in sorted(by_category.items())
    ]
    every = [v for values in by_category.values() for v in values]
    baseline, measured, reduction = weighted_reduction(per_category)
    return ReviewTime(
        decisions=len(every),
        median_seconds=median(every),
        p90_seconds=percentile(every, 90),
        low_sample=len(every) < LOW_SAMPLE,
        categories=per_category,
        weighted_baseline_seconds=baseline,
        weighted_measured_seconds=measured,
        reduction_pct=reduction,
        categories_without_baseline=[
            c.category for c in per_category if c.baseline_seconds is None
        ],
    )
