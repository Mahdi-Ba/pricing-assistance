"""The recommendation engine: a pure, deterministic function (design D7, task 9.2).

``recommend(inputs, rule)`` uses no clock, no I/O and no floats: money is integer Rial, ratios
are integer basis points and intermediate values are exact fractions. Same inputs, same output.

Evaluation order:

1. No valid cost → ``missing_cost``; no complete rule with a VAT rate → ``tax_basis_unset``.
2. Candidate offers: confirmed match, condition-equivalent, in stock, valid price, fresh for the
   variant's tier, approved source, seller allowed by the rule's competitor set.
3. Outliers: a candidate more than ``outlier_threshold`` below the median of at least two other
   candidates is excluded unless an expert confirmed that observation.
4. Too few qualifying offers → ``insufficient_data`` (pending_review > stale_evidence >
   below_min_offers > no_offers).
5. ``floor = ceil_step(cost ÷ (1 − margin − fee) × (1 + VAT))``.
6. ``market_ref = min(qualifying)``; below the floor → ``floor_conflict``.
7. Within hold tolerance → ``hold``.
8. ``target = market_ref − undercut``, clamped to ``[floor, ceiling]``, rounded up to the step
   (ceiling if rounding would pass it). Equal to our price → ``hold``; otherwise ``decrease`` or
   ``increase``; a rounded decrease no longer below the market carries ``undercut_lost``.
"""

import statistics
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from fractions import Fraction

from pricing_assistant.catalog.api import ImportanceTier, ResolvedRule

ENGINE_VERSION = "1.0.0"
BP = 10_000


class Outcome(StrEnum):
    INCREASE = "increase"
    DECREASE = "decrease"
    HOLD = "hold"
    INSUFFICIENT_DATA = "insufficient_data"
    FLOOR_CONFLICT = "floor_conflict"


class Reason(StrEnum):
    ABOVE_MARKET = "above_market"
    BELOW_MARKET = "below_market"
    CAPPED_BY_CEILING = "capped_by_ceiling"
    WITHIN_TOLERANCE = "within_tolerance"
    NO_CHANGE_AFTER_ROUNDING = "no_change_after_rounding"
    MARKET_BELOW_FLOOR = "market_below_floor"
    MISSING_COST = "missing_cost"
    TAX_BASIS_UNSET = "tax_basis_unset"
    MISSING_CURRENT_PRICE = "missing_current_price"
    PENDING_REVIEW = "pending_review"
    STALE_EVIDENCE = "stale_evidence"
    BELOW_MIN_OFFERS = "below_min_offers"
    NO_OFFERS = "no_offers"


class Flag(StrEnum):
    UNDERCUT_LOST = "undercut_lost"
    LIMITED_BY_FLOOR = "limited_by_floor"


ACTIONABLE = frozenset({Outcome.INCREASE, Outcome.DECREASE})


@dataclass(frozen=True, slots=True)
class OfferInput:
    """One market offer's newest observation and its match, as the engine sees it."""

    observation_id: uuid.UUID
    source_id: uuid.UUID
    seller: str | None
    price_rial: int | None
    in_stock: bool
    valid: bool  # not suspect_unit
    observed_at: datetime
    match_version_id: uuid.UUID
    match_confirmed: bool
    match_pending: bool  # proposed or needs_review
    condition_equivalent: bool
    source_approved: bool
    outlier_confirmed: bool = False


@dataclass(frozen=True, slots=True)
class RecommendationInputs:
    variant_id: uuid.UUID
    tier: ImportanceTier
    our_price_rial: int | None
    effective_cost_rial: int | None
    evaluated_at: datetime
    offers: tuple[OfferInput, ...] = ()


@dataclass(frozen=True, slots=True)
class RecommendationResult:
    outcome: Outcome
    reason: Reason
    suggested_price_rial: int | None = None
    floor_rial: int | None = None
    ceiling_rial: int | None = None
    market_ref_rial: int | None = None
    market_ref_observation_id: uuid.UUID | None = None
    median_rial: int | None = None
    qualifying_observation_ids: tuple[uuid.UUID, ...] = ()
    excluded_outlier_ids: tuple[uuid.UUID, ...] = ()
    flags: tuple[Flag, ...] = ()
    profit_current_rial: int | None = None
    profit_suggested_rial: int | None = None
    engine_version: str = ENGINE_VERSION
    notes: dict[str, str] = field(default_factory=dict)

    @property
    def qualifying_count(self) -> int:
        return len(self.qualifying_observation_ids)


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def ceil_to_step(value: Fraction | int, step: int) -> int:
    value = Fraction(value)
    return ceil_div(value.numerator, value.denominator * step) * step


def floor_exact(cost_rial: int, rule: ResolvedRule) -> Fraction:
    """cost ÷ (1 − margin − fee) × (1 + VAT), exact."""
    net = Fraction(cost_rial * BP, BP - rule.min_margin_bp - rule.fee_rate_bp)
    return net * Fraction(BP + rule.vat_rate_bp, BP)


def floor_price(cost_rial: int, rule: ResolvedRule) -> int:
    return ceil_to_step(floor_exact(cost_rial, rule), rule.rounding_step_rial)


def unit_profit(price_rial: int, cost_rial: int, rule: ResolvedRule) -> int:
    """price ÷ (1 + VAT) × (1 − fee) − cost, truncated to whole Rial."""
    net = Fraction(price_rial * BP, BP + rule.vat_rate_bp) * Fraction(BP - rule.fee_rate_bp, BP)
    return int(net - cost_rial)  # int() truncates toward zero; Fractions are exact before this


def _is_fresh(offer: OfferInput, inputs: RecommendationInputs, rule: ResolvedRule) -> bool:
    age = (inputs.evaluated_at - offer.observed_at).total_seconds()
    return age <= rule.max_data_age_seconds[inputs.tier]


def _candidates(inputs: RecommendationInputs, rule: ResolvedRule) -> list[OfferInput]:
    return [
        o
        for o in inputs.offers
        if o.match_confirmed
        and o.condition_equivalent
        and o.in_stock
        and o.valid
        and o.price_rial is not None
        and o.source_approved
        and rule.allows_seller(o.source_id, o.seller)
        and _is_fresh(o, inputs, rule)
    ]


class Disqualification(StrEnum):
    """Why an offer did not count toward the market reference (shown in the evidence table)."""

    MATCH_PENDING = "match_pending"
    MATCH_NOT_CONFIRMED = "match_not_confirmed"
    CONDITION_MISMATCH = "condition_mismatch"
    OUT_OF_STOCK = "out_of_stock"
    INVALID_PRICE = "invalid_price"
    SOURCE_NOT_APPROVED = "source_not_approved"
    OUTSIDE_COMPETITOR_SET = "outside_competitor_set"
    STALE = "stale"
    PRICE_OUTLIER = "price_outlier"


def disqualifications(
    offer: OfferInput,
    inputs: RecommendationInputs,
    rule: ResolvedRule | None,
    excluded_outlier_ids: tuple[uuid.UUID, ...] = (),
) -> list[Disqualification]:
    """Every reason the offer was not a qualifying offer; empty when it qualified.

    Mirrors :func:`_candidates` and the outlier step, so it explains exactly what ``recommend``
    did. Seller and freshness checks need the rule and are skipped without one.
    """
    reasons: list[Disqualification] = []
    if not offer.match_confirmed:
        reasons.append(
            Disqualification.MATCH_PENDING
            if offer.match_pending
            else Disqualification.MATCH_NOT_CONFIRMED
        )
    if not offer.condition_equivalent:
        reasons.append(Disqualification.CONDITION_MISMATCH)
    if not offer.in_stock:
        reasons.append(Disqualification.OUT_OF_STOCK)
    if not offer.valid or offer.price_rial is None:
        reasons.append(Disqualification.INVALID_PRICE)
    if not offer.source_approved:
        reasons.append(Disqualification.SOURCE_NOT_APPROVED)
    if rule is not None:
        if not rule.allows_seller(offer.source_id, offer.seller):
            reasons.append(Disqualification.OUTSIDE_COMPETITOR_SET)
        if not _is_fresh(offer, inputs, rule):
            reasons.append(Disqualification.STALE)
    if offer.observation_id in excluded_outlier_ids:
        reasons.append(Disqualification.PRICE_OUTLIER)
    return reasons


def _split_outliers(
    candidates: list[OfferInput], threshold_bp: int
) -> tuple[list[OfferInput], list[OfferInput]]:
    qualifying: list[OfferInput] = []
    outliers: list[OfferInput] = []
    for offer in candidates:
        others = [o.price_rial for o in candidates if o is not offer and o.price_rial is not None]
        assert offer.price_rial is not None  # noqa: S101 - candidates always have a price
        is_outlier = (
            len(others) >= 2  # noqa: PLR2004 - spec: at least two other offers
            and Fraction(offer.price_rial)
            < Fraction(statistics.median(others)) * Fraction(BP - threshold_bp, BP)
            and not offer.outlier_confirmed
        )
        (outliers if is_outlier else qualifying).append(offer)
    return qualifying, outliers


def _insufficient_reason(
    inputs: RecommendationInputs,
    rule: ResolvedRule,
    qualifying: list[OfferInput],
    outliers: list[OfferInput],
) -> Reason:
    if outliers or any(o.match_pending for o in inputs.offers):
        return Reason.PENDING_REVIEW
    usable_but_stale = [
        o
        for o in inputs.offers
        if o.match_confirmed
        and o.condition_equivalent
        and o.in_stock
        and o.valid
        and o.source_approved
        and o.price_rial is not None
        and not _is_fresh(o, inputs, rule)
    ]
    if usable_but_stale:
        return Reason.STALE_EVIDENCE
    if qualifying:
        return Reason.BELOW_MIN_OFFERS
    return Reason.NO_OFFERS


def _target_price(market_ref: int, floor: int, rule: ResolvedRule) -> tuple[int, list[Flag], bool]:
    """market − undercut, clamped to [floor, ceiling], rounded up to the step."""
    flags: list[Flag] = []
    target = market_ref - rule.undercut_step_rial
    if target < floor:
        target = floor
        flags.append(Flag.LIMITED_BY_FLOOR)
    ceiling = rule.ceiling_rial
    capped = ceiling is not None and target > ceiling
    if ceiling is not None and capped:
        target = ceiling
    suggested = ceil_to_step(target, rule.rounding_step_rial)
    if ceiling is not None and suggested > ceiling:
        suggested, capped = ceiling, True
    return max(suggested, floor), flags, capped


def recommend(inputs: RecommendationInputs, rule: ResolvedRule | None) -> RecommendationResult:
    cost = inputs.effective_cost_rial
    if cost is None or cost <= 0:
        return RecommendationResult(Outcome.INSUFFICIENT_DATA, Reason.MISSING_COST)
    if rule is None:
        return RecommendationResult(Outcome.INSUFFICIENT_DATA, Reason.TAX_BASIS_UNSET)

    floor = floor_price(cost, rule)
    qualifying, outliers = _split_outliers(_candidates(inputs, rule), rule.outlier_threshold_bp)
    base = RecommendationResult(
        Outcome.INSUFFICIENT_DATA,
        Reason.NO_OFFERS,
        floor_rial=floor,
        ceiling_rial=rule.ceiling_rial,
        excluded_outlier_ids=tuple(o.observation_id for o in outliers),
        qualifying_observation_ids=tuple(o.observation_id for o in qualifying),
    )
    if not qualifying or len(qualifying) < rule.min_qualifying_offers:
        return replace(base, reason=_insufficient_reason(inputs, rule, qualifying, outliers))

    reference = min(qualifying, key=lambda o: (o.price_rial or 0, str(o.observation_id)))
    market_ref = reference.price_rial or 0
    base = replace(
        base,
        market_ref_rial=market_ref,
        market_ref_observation_id=reference.observation_id,
        median_rial=int(statistics.median([o.price_rial or 0 for o in qualifying])),
    )
    if market_ref < floor:
        return replace(base, outcome=Outcome.FLOOR_CONFLICT, reason=Reason.MARKET_BELOW_FLOOR)

    our = inputs.our_price_rial
    if our is None:
        return replace(base, reason=Reason.MISSING_CURRENT_PRICE)
    base = replace(base, outcome=Outcome.HOLD, profit_current_rial=unit_profit(our, cost, rule))
    if abs(our - market_ref) * BP <= rule.hold_tolerance_bp * market_ref:
        return replace(base, reason=Reason.WITHIN_TOLERANCE)

    suggested, flags, capped = _target_price(market_ref, floor, rule)
    if suggested == our:
        return replace(base, reason=Reason.NO_CHANGE_AFTER_ROUNDING)
    outcome = Outcome.DECREASE if suggested < our else Outcome.INCREASE
    if outcome is Outcome.DECREASE and suggested >= market_ref:
        flags.append(Flag.UNDERCUT_LOST)
    if capped and outcome is Outcome.INCREASE:
        reason = Reason.CAPPED_BY_CEILING
    else:
        reason = Reason.ABOVE_MARKET if outcome is Outcome.DECREASE else Reason.BELOW_MARKET
    return replace(
        base,
        outcome=outcome,
        reason=reason,
        suggested_price_rial=suggested,
        flags=tuple(flags),
        profit_suggested_rial=unit_profit(suggested, cost, rule),
    )
