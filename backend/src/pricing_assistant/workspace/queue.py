"""The review queue read model (tasks 11.1–11.3).

One item per variant with a current recommendation. The read model is computed on request from
the system of record (current recommendations, decisions, offer freshness), so it is always
consistent with them; it holds no state of its own.

Status comes from the decision that applies to the item:

- a decision on the current recommendation → its status (an override the admin rejected counts
  as ``needs_review`` again — a new decision is needed);
- otherwise a decision on an earlier version that is still being verified on our site;
- otherwise ``needs_review``.

``verified`` items are closed and left out unless that status is asked for explicitly.

Priority score (higher first) = tier multiplier × (outcome weight + profit-impact points + age
points). Every input is returned with the item.
"""

import base64
import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.api import (
    ImportanceTier,
    ResolvedRule,
    VariantInfo,
    list_variants,
    resolve_for_variants,
)
from pricing_assistant.collection.api import (
    FetchAttemptRow,
    Freshness,
    ObservationRow,
    Validity,
    classify,
)
from pricing_assistant.core.errors import ValidationFailed
from pricing_assistant.decisions.api import (
    DecisionOutcomeRow,
    DecisionRow,
    DecisionStatus,
    Stage,
    decision_views,
)
from pricing_assistant.pricing.api import Outcome, Reason, RecommendationRow
from pricing_assistant.sources.api import TrackedOfferRow, TrackedOfferStatus

TIER_MULTIPLIER = {ImportanceTier.A: 3, ImportanceTier.B: 2, ImportanceTier.C: 1}
OUTCOME_WEIGHT = {
    Outcome.FLOOR_CONFLICT: 100,
    Outcome.DECREASE: 80,
    Outcome.INCREASE: 50,
    Outcome.INSUFFICIENT_DATA: 30,
    Outcome.HOLD: 10,
}
MAX_PROFIT_POINTS = 50
MAX_AGE_POINTS = 24  # one point per open hour, capped at a day
DEFAULT_PAGE = 50
MAX_PAGE = 200


class QueueStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"  # نیازمند بررسی
    AWAITING_OVERRIDE = "awaiting_override"  # در انتظار تأیید مدیر
    DECIDED = "decided"  # تصمیم ثبت شد
    AWAITING_VERIFICATION = "awaiting_verification"  # در انتظار تأیید روی سایت
    VERIFICATION_OVERDUE = "verification_overdue"  # تأیید روی سایت دیر شده
    VERIFIED = "verified"  # closed


OPEN_STATUSES = frozenset(QueueStatus) - {QueueStatus.VERIFIED}


class Alert(StrEnum):
    FLOOR_CONFLICT = "floor_conflict"
    SOURCE_FAILURE = "source_failure"
    STALE_DATA = "stale_data"


class SourceHealthFilter(StrEnum):
    ATTENTION = "attention"  # any failure or stale data
    FAILING = "failing"
    STALE = "stale"
    OK = "ok"


class PricePosition(StrEnum):
    ABOVE_MARKET = "above_market"  # decrease/floor_conflict because our price > market reference
    BELOW_MARKET = "below_market"  # increase because our price < market reference


_FROM_DECISION = {
    DecisionStatus.DECIDED: QueueStatus.DECIDED,
    DecisionStatus.OVERRIDE_PENDING: QueueStatus.AWAITING_OVERRIDE,
    DecisionStatus.OVERRIDE_REJECTED: QueueStatus.NEEDS_REVIEW,
    DecisionStatus.AWAITING_VERIFICATION: QueueStatus.AWAITING_VERIFICATION,
    DecisionStatus.VERIFICATION_OVERDUE: QueueStatus.VERIFICATION_OVERDUE,
    DecisionStatus.VERIFIED: QueueStatus.VERIFIED,
}


@dataclass(frozen=True, slots=True)
class ScoreInputs:
    tier: ImportanceTier
    tier_multiplier: int
    outcome: Outcome
    outcome_weight: int
    profit_impact_rial: int
    profit_points: int
    open_since: datetime
    age_hours: int
    age_points: int
    score: int


@dataclass(frozen=True, slots=True)
class QueueItem:
    variant: VariantInfo
    recommendation: RecommendationRow
    status: QueueStatus
    decision_id: uuid.UUID | None
    alerts: tuple[Alert, ...]
    market_label: str | None  # "stale" / "failed" when no usable market reference
    score: ScoreInputs

    @property
    def sort_key(self) -> tuple[int, str]:
        return (self.score.score, str(self.variant.id))


@dataclass(frozen=True, slots=True)
class QueueFilter:
    categories: frozenset[str] = frozenset()
    tiers: frozenset[ImportanceTier] = frozenset()
    outcomes: frozenset[Outcome] = frozenset()
    statuses: frozenset[QueueStatus] = frozenset()
    source_health: SourceHealthFilter | None = None
    price_position: PricePosition | None = None

    def matches(self, item: QueueItem) -> bool:
        rec = item.recommendation
        if self.categories and item.variant.category not in self.categories:
            return False
        if self.tiers and item.variant.importance_tier not in self.tiers:
            return False
        if self.outcomes and Outcome(rec.outcome) not in self.outcomes:
            return False
        if item.status not in (self.statuses or OPEN_STATUSES):
            return False
        if self.source_health is not None and not _health_matches(self.source_health, item):
            return False
        return self.price_position is None or _position_matches(self.price_position, item)


def _health_matches(wanted: SourceHealthFilter, item: QueueItem) -> bool:
    failing = Alert.SOURCE_FAILURE in item.alerts
    stale = Alert.STALE_DATA in item.alerts
    return {
        SourceHealthFilter.ATTENTION: failing or stale,
        SourceHealthFilter.FAILING: failing,
        SourceHealthFilter.STALE: stale,
        SourceHealthFilter.OK: not (failing or stale),
    }[wanted]


def _position_matches(wanted: PricePosition, item: QueueItem) -> bool:
    rec = item.recommendation
    ours, market = rec.our_price_rial, rec.market_ref_rial
    if ours is None or market is None:
        return False
    if wanted is PricePosition.ABOVE_MARKET:
        return (
            rec.outcome in (Outcome.DECREASE.value, Outcome.FLOOR_CONFLICT.value) and ours > market
        )
    return rec.outcome == Outcome.INCREASE.value and ours < market


# --- score --------------------------------------------------------------------------------------


def profit_impact(rec: RecommendationRow) -> int:
    """Absolute estimated per-unit impact in Rial: the proposed change, else the market gap."""
    if rec.suggested_price_rial is not None and rec.our_price_rial is not None:
        return abs(rec.suggested_price_rial - rec.our_price_rial)
    if rec.market_ref_rial is not None and rec.our_price_rial is not None:
        return abs(rec.market_ref_rial - rec.our_price_rial)
    return 0


def score(
    tier: ImportanceTier, rec: RecommendationRow, open_since: datetime, now: datetime
) -> ScoreInputs:
    impact = profit_impact(rec)
    # 10 points per tenfold impact, from 100,000 Rial (10,000 Toman) upward
    profit_points = min(MAX_PROFIT_POINTS, max(0, int(10 * math.log10(1 + impact / 100_000))))
    age_hours = max(0, int((now - open_since).total_seconds() // 3600))
    age_points = min(MAX_AGE_POINTS, age_hours)
    outcome = Outcome(rec.outcome)
    weight = OUTCOME_WEIGHT[outcome]
    multiplier = TIER_MULTIPLIER[tier]
    return ScoreInputs(
        tier=tier,
        tier_multiplier=multiplier,
        outcome=outcome,
        outcome_weight=weight,
        profit_impact_rial=impact,
        profit_points=profit_points,
        open_since=open_since,
        age_hours=age_hours,
        age_points=age_points,
        score=multiplier * (weight + profit_points + age_points),
    )


# --- loading ------------------------------------------------------------------------------------


async def _current_recommendations(session: AsyncSession) -> dict[uuid.UUID, RecommendationRow]:
    rows = await session.scalars(
        select(RecommendationRow).where(RecommendationRow.superseded_by.is_(None))
    )
    return {r.variant_id: r for r in rows.all()}


async def _open_since(session: AsyncSession) -> dict[uuid.UUID, datetime]:
    """Per variant: the first recommendation after its latest decision."""
    last_decision = (
        select(DecisionRow.variant_id, func.max(DecisionRow.created_at).label("last"))
        .group_by(DecisionRow.variant_id)
        .subquery()
    )
    rows = await session.execute(
        select(RecommendationRow.variant_id, func.min(RecommendationRow.created_at))
        .outerjoin(last_decision, last_decision.c.variant_id == RecommendationRow.variant_id)
        .where(
            (last_decision.c.last.is_(None)) | (RecommendationRow.created_at > last_decision.c.last)
        )
        .group_by(RecommendationRow.variant_id)
    )
    return {variant_id: opened for variant_id, opened in rows.all()}


async def _statuses(
    session: AsyncSession, current: dict[uuid.UUID, RecommendationRow]
) -> dict[uuid.UUID, tuple[QueueStatus, uuid.UUID]]:
    superseded = select(DecisionRow.supersedes_decision_id).where(
        DecisionRow.supersedes_decision_id.is_not(None)
    )
    on_current = list(
        (
            await session.scalars(
                select(DecisionRow).where(
                    DecisionRow.recommendation_id.in_([r.id for r in current.values()]),
                    DecisionRow.id.not_in(superseded),
                )
            )
        ).all()
    )
    verified = select(DecisionOutcomeRow.decision_id).where(
        DecisionOutcomeRow.stage == Stage.OBSERVED_ON_SITE.value
    )
    reported = select(DecisionOutcomeRow.decision_id).where(
        DecisionOutcomeRow.stage == Stage.REPORTED_DONE.value
    )
    in_verification = list(
        (
            await session.scalars(
                select(DecisionRow)
                .where(
                    DecisionRow.id.in_(reported),
                    DecisionRow.id.not_in(verified),
                    DecisionRow.id.not_in(superseded),
                )
                .order_by(DecisionRow.created_at)
            )
        ).all()
    )
    views = await decision_views(session, on_current + in_verification)
    result: dict[uuid.UUID, tuple[QueueStatus, uuid.UUID]] = {}
    for decision in in_verification:  # earlier versions, overridden below by the current one
        result[decision.variant_id] = (_FROM_DECISION[views[decision.id].status], decision.id)
    for decision in on_current:
        result[decision.variant_id] = (_FROM_DECISION[views[decision.id].status], decision.id)
    return result


async def _freshness(
    session: AsyncSession,
    variants: dict[uuid.UUID, VariantInfo],
    rules: dict[uuid.UUID, ResolvedRule | None],
    now: datetime,
) -> dict[uuid.UUID, list[Freshness]]:
    offers = (
        await session.scalars(
            select(TrackedOfferRow).where(
                TrackedOfferRow.status == TrackedOfferStatus.ACTIVE.value,
                TrackedOfferRow.is_own_store.is_(False),
                TrackedOfferRow.is_own_channel.is_(False),
            )
        )
    ).all()
    observed = dict(
        (
            await session.execute(
                select(ObservationRow.tracked_offer_id, func.max(ObservationRow.observed_at))
                .where(ObservationRow.validity == Validity.VALID.value)
                .group_by(ObservationRow.tracked_offer_id)
            )
        ).all()
    )
    failed = dict(
        (
            await session.execute(
                select(FetchAttemptRow.tracked_offer_id, func.max(FetchAttemptRow.finished_at))
                .where(FetchAttemptRow.outcome == "failure", FetchAttemptRow.final.is_(True))
                .group_by(FetchAttemptRow.tracked_offer_id)
            )
        ).all()
    )
    states: dict[uuid.UUID, list[Freshness]] = {}
    for offer in offers:
        variant = variants.get(offer.variant_id)
        rule = rules.get(offer.variant_id)
        if variant is None or rule is None:
            continue
        states.setdefault(offer.variant_id, []).append(
            classify(
                last_observed_at=observed.get(offer.id),
                last_failure_at=failed.get(offer.id),
                max_age_seconds=rule.max_data_age_seconds[variant.importance_tier],
                now=now,
            )
        )
    return states


def _alerts(rec: RecommendationRow, freshness: Sequence[Freshness]) -> tuple[Alert, ...]:
    alerts: list[Alert] = []
    if rec.outcome == Outcome.FLOOR_CONFLICT.value:
        alerts.append(Alert.FLOOR_CONFLICT)
    if Freshness.FAILED in freshness:
        alerts.append(Alert.SOURCE_FAILURE)
    if Freshness.STALE in freshness or rec.reason_code == Reason.STALE_EVIDENCE.value:
        alerts.append(Alert.STALE_DATA)
    return tuple(alerts)


def _market_label(rec: RecommendationRow, freshness: Sequence[Freshness]) -> str | None:
    if rec.market_ref_rial is not None:
        return None
    if freshness and all(f is Freshness.FAILED for f in freshness):
        return "failed"
    if rec.reason_code == Reason.STALE_EVIDENCE.value or Freshness.STALE in freshness:
        return "stale"
    return None


async def load_queue(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    variant_ids: set[uuid.UUID] | None = None,
) -> list[QueueItem]:
    """Every item (all statuses), highest priority first; optionally only ``variant_ids``."""
    now = now or datetime.now(UTC)
    current = await _current_recommendations(session)
    if variant_ids is not None:
        current = {k: v for k, v in current.items() if k in variant_ids}
    if not current:
        return []
    variants = {v.id: v for v in await list_variants(session) if v.id in current}
    rules = await resolve_for_variants(session, ((v.id, v.category) for v in variants.values()))
    statuses = await _statuses(session, current)
    opened = await _open_since(session)
    freshness = await _freshness(session, variants, rules, now)
    items = []
    for variant_id, rec in current.items():
        variant = variants.get(variant_id)
        if variant is None:
            continue
        status, decision_id = statuses.get(variant_id, (QueueStatus.NEEDS_REVIEW, None))
        states = freshness.get(variant_id, [])
        items.append(
            QueueItem(
                variant=variant,
                recommendation=rec,
                status=status,
                decision_id=decision_id,
                alerts=_alerts(rec, states),
                market_label=_market_label(rec, states),
                score=score(
                    variant.importance_tier, rec, opened.get(variant_id, rec.created_at), now
                ),
            )
        )
    return sorted(items, key=lambda i: i.sort_key, reverse=True)


# --- pagination ---------------------------------------------------------------------------------


def encode_cursor(item: QueueItem) -> str:
    return base64.urlsafe_b64encode(f"{item.score.score}:{item.variant.id}".encode()).decode()


def decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        score_text, variant_id = base64.urlsafe_b64decode(cursor.encode()).decode().split(":", 1)
        return int(score_text), str(uuid.UUID(variant_id))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationFailed("Invalid cursor", message_fa="نشانگر صفحه معتبر نیست.") from exc


@dataclass(frozen=True, slots=True)
class QueuePage:
    items: list[QueueItem]
    total: int
    next_cursor: str | None


def page(
    items: Iterable[QueueItem], flt: QueueFilter, *, limit: int, cursor: str | None
) -> QueuePage:
    matching = [i for i in items if flt.matches(i)]
    start = 0
    if cursor is not None:
        after = decode_cursor(cursor)
        start = next((n for n, i in enumerate(matching) if i.sort_key < after), len(matching))
    chunk = matching[start : start + limit]
    more = start + limit < len(matching)
    return QueuePage(
        items=chunk,
        total=len(matching),
        next_cursor=encode_cursor(chunk[-1]) if more and chunk else None,
    )


# --- summary cards ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Card:
    key: str
    title_fa: str
    filter: QueueFilter = field(default_factory=QueueFilter)
    admin_only: bool = False
    primary: bool = False


CARDS: tuple[Card, ...] = (
    Card(
        "open_decisions",
        "تصمیم‌های باز",
        QueueFilter(statuses=frozenset({QueueStatus.NEEDS_REVIEW})),
        primary=True,
    ),
    Card(
        "above_market",
        "گران‌تر از بازار",
        QueueFilter(price_position=PricePosition.ABOVE_MARKET),
    ),
    Card(
        "below_market",
        "ارزان‌تر از بازار",
        QueueFilter(price_position=PricePosition.BELOW_MARKET),
    ),
    Card(
        "floor_conflicts",
        "تعارض با کف سود",
        QueueFilter(outcomes=frozenset({Outcome.FLOOR_CONFLICT})),
    ),
    Card(
        "source_attention",
        "منابع قدیمی / ناموفق",
        QueueFilter(source_health=SourceHealthFilter.ATTENTION),
    ),
    Card(
        "overrides_awaiting_approval",
        "قیمت‌های زیر کف در انتظار تأیید",
        QueueFilter(statuses=frozenset({QueueStatus.AWAITING_OVERRIDE})),
        admin_only=True,
    ),
)


def card_counts(items: Sequence[QueueItem], *, is_admin: bool) -> list[tuple[Card, int]]:
    return [
        (card, sum(1 for item in items if card.filter.matches(item)))
        for card in CARDS
        if is_admin or not card.admin_only
    ]
