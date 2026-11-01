"""Property-based invariants of the engine (task 9.3)."""

import uuid
from datetime import timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pricing_assistant.catalog.api import ImportanceTier
from pricing_assistant.pricing.engine import ACTIONABLE, Outcome, recommend
from tests.support.engine import NOW, inputs, offer, rule

money = st.integers(min_value=1_000_000, max_value=2_000_000_000)


@st.composite
def scenario(draw: st.DrawFn) -> tuple[object, object]:
    margin = draw(st.integers(0, 3_000))
    fee = draw(st.integers(0, 2_000))
    r = rule(
        min_margin_bp=margin,
        fee_rate_bp=fee,
        vat_rate_bp=draw(st.integers(0, 1_500)),
        undercut_step_rial=draw(st.integers(1, 2_000_000)),
        hold_tolerance_bp=draw(st.integers(0, 500)),
        rounding_step_rial=draw(st.sampled_from([1, 1_000, 10_000, 100_000, 1_000_000])),
        ceiling_rial=draw(st.none() | money),
        outlier_threshold_bp=draw(st.integers(0, 5_000)),
        min_qualifying_offers=draw(st.integers(1, 3)),
    )
    offers = [
        offer(
            draw(money),
            in_stock=draw(st.booleans()),
            outlier_confirmed=draw(st.booleans()),
            observed_at=NOW - timedelta(minutes=draw(st.integers(0, 300))),
            observation_id=uuid.UUID(int=i + 1),
        )
        for i in range(draw(st.integers(0, 6)))
    ]
    data = inputs(
        *offers,
        our=draw(st.none() | money),
        cost=draw(st.none() | st.integers(1, 1_500_000_000)),
        tier=draw(st.sampled_from(list(ImportanceTier))),
    )
    return data, r


@settings(max_examples=10_000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(scenario())
def test_engine_invariants(case: tuple[object, object]) -> None:
    data, r = case
    result = recommend(data, r)  # type: ignore[arg-type]
    assert recommend(data, r) == result  # type: ignore[arg-type]  # deterministic
    if result.outcome in ACTIONABLE:
        assert result.suggested_price_rial is not None
        assert result.floor_rial is not None
        assert result.suggested_price_rial >= result.floor_rial  # never below the floor
        if (
            result.outcome is Outcome.INCREASE
            and result.ceiling_rial is not None
            and result.ceiling_rial >= result.floor_rial
        ):
            assert result.suggested_price_rial <= result.ceiling_rial
        step = r.rounding_step_rial  # type: ignore[attr-defined]
        assert result.suggested_price_rial % step == 0 or result.suggested_price_rial in (
            result.ceiling_rial,
            result.floor_rial,
        )
    else:
        assert result.suggested_price_rial is None
    if result.market_ref_observation_id is not None:
        assert result.market_ref_observation_id not in result.excluded_outlier_ids
