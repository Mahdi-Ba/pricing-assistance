"""Every scenario of specs/price-recommendation as an engine unit test (task 9.2)."""

from datetime import timedelta

from pricing_assistant.catalog.api import ImportanceTier
from pricing_assistant.pricing.engine import (
    Flag,
    Outcome,
    Reason,
    floor_exact,
    floor_price,
    recommend,
)
from tests.support.engine import NOW, SOURCE, inputs, offer, rule


def test_cheaper_comparable_competitor_decrease() -> None:
    # floor 84,000,000: cost 75,600,000 at 10% margin
    result = recommend(inputs(offer(86_000_000), cost=75_600_000), rule(undercut_step_rial=500_000))
    assert result.floor_rial == 84_000_000
    assert (result.outcome, result.suggested_price_rial, result.reason) == (
        Outcome.DECREASE,
        85_500_000,
        Reason.ABOVE_MARKET,
    )


def test_we_are_cheaper_increase() -> None:
    result = recommend(
        inputs(offer(86_000_000), our=82_000_000, cost=72_000_000),
        rule(undercut_step_rial=500_000, hold_tolerance_bp=100),
    )
    assert result.floor_rial == 80_000_000
    assert (result.outcome, result.suggested_price_rial, result.reason) == (
        Outcome.INCREASE,
        85_500_000,
        Reason.BELOW_MARKET,
    )


def test_floor_10_percent_margin_no_fees() -> None:
    assert floor_price(90_000_000, rule(min_margin_bp=1_000, fee_rate_bp=0)) == 100_000_000


def test_floor_with_percentage_fee() -> None:
    r = rule(min_margin_bp=1_000, fee_rate_bp=500)
    assert float(floor_exact(90_000_000, r)) == 105_882_352.94117647
    assert floor_price(90_000_000, r) == 105_882_353
    assert (
        floor_price(
            90_000_000, rule(min_margin_bp=1_000, fee_rate_bp=500, rounding_step_rial=100_000)
        )
        == 105_900_000
    )


def test_floor_vat_inclusive() -> None:
    assert floor_exact(90_000_000, rule(vat_rate_bp=1_000)) == 110_000_000


def test_vat_basis_not_configured() -> None:
    result = recommend(inputs(offer(86_000_000)), None)
    assert (result.outcome, result.reason) == (Outcome.INSUFFICIENT_DATA, Reason.TAX_BASIS_UNSET)


def test_market_below_floor_is_floor_conflict() -> None:
    result = recommend(inputs(offer(82_000_000), cost=75_600_000), rule())
    assert result.outcome is Outcome.FLOOR_CONFLICT
    assert result.suggested_price_rial is None
    assert (result.floor_rial, result.market_ref_rial) == (84_000_000, 82_000_000)


def test_increase_capped_by_ceiling() -> None:
    result = recommend(
        inputs(offer(120_500_000), our=100_000_000, cost=70_000_000),
        rule(ceiling_rial=115_000_000, undercut_step_rial=500_000),
    )
    assert (result.outcome, result.suggested_price_rial, result.reason) == (
        Outcome.INCREASE,
        115_000_000,
        Reason.CAPPED_BY_CEILING,
    )


def test_out_of_stock_offer_ignored() -> None:
    result = recommend(
        inputs(offer(80_000_000, in_stock=False), offer(86_000_000)),
        rule(undercut_step_rial=500_000),
    )
    assert result.market_ref_rial == 86_000_000


def test_seller_outside_competitor_set_ignored() -> None:
    r = rule(competitor_set={str(SOURCE): ["S1", "S2"]})
    result = recommend(inputs(offer(80_000_000, seller="S3"), offer(86_000_000, seller="S1")), r)
    assert result.market_ref_rial == 86_000_000


def test_outlier_excluded_and_confirmed() -> None:
    low = offer(70_000_000)
    others = (offer(86_000_000), offer(87_000_000))
    result = recommend(inputs(low, *others), rule(outlier_threshold_bp=1_500))
    assert result.market_ref_rial == 86_000_000
    assert result.excluded_outlier_ids == (low.observation_id,)
    confirmed = recommend(
        inputs(offer(70_000_000, outlier_confirmed=True), *others, cost=50_000_000), rule()
    )
    assert confirmed.market_ref_rial == 70_000_000


def test_hold_within_tolerance() -> None:
    result = recommend(inputs(offer(86_000_000), our=86_430_000), rule(hold_tolerance_bp=100))
    assert (result.outcome, result.reason) == (Outcome.HOLD, Reason.WITHIN_TOLERANCE)


def test_rounded_up_to_step() -> None:
    result = recommend(
        inputs(offer(85_990_000)), rule(undercut_step_rial=500_000, rounding_step_rial=100_000)
    )
    assert result.suggested_price_rial == 85_500_000


def test_undercut_lost_by_rounding() -> None:
    result = recommend(
        inputs(offer(85_980_000), cost=75_600_000),
        rule(undercut_step_rial=50_000, rounding_step_rial=100_000),
    )
    assert (result.outcome, result.suggested_price_rial) == (Outcome.DECREASE, 86_000_000)
    assert Flag.UNDERCUT_LOST in result.flags


def test_no_change_after_rounding() -> None:
    result = recommend(
        inputs(offer(86_480_000), our=86_000_000, cost=60_000_000),
        rule(undercut_step_rial=500_000, rounding_step_rial=100_000, hold_tolerance_bp=0),
    )
    assert (result.outcome, result.reason) == (Outcome.HOLD, Reason.NO_CHANGE_AFTER_ROUNDING)


def test_only_stale_evidence() -> None:
    stale = offer(86_000_000, observed_at=NOW - timedelta(hours=3))
    result = recommend(inputs(stale), rule())
    assert (result.outcome, result.reason) == (Outcome.INSUFFICIENT_DATA, Reason.STALE_EVIDENCE)
    tier_c = recommend(
        inputs(offer(86_000_000, observed_at=NOW - timedelta(hours=6)), tier=ImportanceTier.C),
        rule(),
    )
    assert tier_c.outcome is not Outcome.INSUFFICIENT_DATA


def test_insufficient_data_precedence() -> None:
    assert recommend(inputs(offer(86_000_000), cost=None), rule()).reason is Reason.MISSING_COST
    pending = offer(86_000_000, match_confirmed=False, match_pending=True)
    assert recommend(inputs(pending), rule()).reason is Reason.PENDING_REVIEW
    assert recommend(inputs(), rule()).reason is Reason.NO_OFFERS
    assert (
        recommend(inputs(offer(86_000_000)), rule(min_qualifying_offers=2)).reason
        is Reason.BELOW_MIN_OFFERS
    )
    mismatch = offer(86_000_000, condition_equivalent=False)
    assert recommend(inputs(mismatch), rule()).reason is Reason.NO_OFFERS
    suspect = offer(8_600_000, valid=False)
    assert recommend(inputs(suspect), rule()).reason is Reason.NO_OFFERS
    unapproved = offer(86_000_000, source_approved=False)
    assert recommend(inputs(unapproved), rule()).reason is Reason.NO_OFFERS


def test_profit_shown() -> None:
    result = recommend(inputs(offer(86_000_000), cost=75_000_000), rule(undercut_step_rial=500_000))
    assert result.suggested_price_rial == 85_500_000
    assert result.profit_suggested_rial == 10_500_000
    assert result.profit_current_rial == 14_000_000


def test_profit_uses_net_price() -> None:
    result = recommend(
        inputs(offer(110_000_000), our=121_000_000, cost=80_000_000),
        rule(vat_rate_bp=1_000, undercut_step_rial=1_100_000),
    )
    assert result.suggested_price_rial == 108_900_000
    assert result.profit_suggested_rial == 19_000_000  # 108.9M / 1.1 − 80M
