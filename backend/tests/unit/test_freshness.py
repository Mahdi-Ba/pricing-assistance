from datetime import UTC, datetime, timedelta

from pricing_assistant.collection.freshness import STALE_OR_FAILED_FA, Freshness, classify

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TWO_HOURS, DAY = 7_200, 86_400


def test_tier_a_observation_ages_out_after_two_hours() -> None:
    state = classify(
        last_observed_at=NOW - timedelta(hours=3),
        last_failure_at=None,
        max_age_seconds=TWO_HOURS,
        now=NOW,
    )
    assert state is Freshness.STALE
    assert state.label_fa == STALE_OR_FAILED_FA


def test_tier_c_has_its_own_limit() -> None:
    state = classify(
        last_observed_at=NOW - timedelta(hours=6),
        last_failure_at=None,
        max_age_seconds=DAY,
        now=NOW,
    )
    assert state is Freshness.FRESH
    assert state.label_fa is None


def test_failure_after_last_success_is_failed_even_if_recent() -> None:
    state = classify(
        last_observed_at=NOW - timedelta(minutes=30),
        last_failure_at=NOW - timedelta(minutes=5),
        max_age_seconds=TWO_HOURS,
        now=NOW,
    )
    assert state is Freshness.FAILED
    assert state.label_fa == STALE_OR_FAILED_FA


def test_success_after_failure_is_fresh_again() -> None:
    state = classify(
        last_observed_at=NOW - timedelta(minutes=1),
        last_failure_at=NOW - timedelta(minutes=20),
        max_age_seconds=TWO_HOURS,
        now=NOW,
    )
    assert state is Freshness.FRESH


def test_never_observed() -> None:
    assert (
        classify(last_observed_at=None, last_failure_at=None, max_age_seconds=TWO_HOURS, now=NOW)
        is Freshness.NEVER_OBSERVED
    )
