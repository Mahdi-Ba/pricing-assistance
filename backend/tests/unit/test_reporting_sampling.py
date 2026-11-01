"""Stratified audit sampling and review-time arithmetic (tasks 13.1, 13.3)."""

import uuid
from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pricing_assistant.reporting.pilot import CategoryReviewTime, weighted_reduction
from pricing_assistant.reporting.sampling import (
    Candidate,
    confidence_band,
    percentile,
    stratified_sample,
)

SOURCES = [uuid.UUID(int=i) for i in range(1, 4)]


def _population(n: int, *, categories: int = 4, skew: bool = True) -> list[Candidate]:
    items = []
    for i in range(n):
        # heavily skewed: most matches are ssd / source 1 / exact identifier
        category = "ssd" if skew and i % 10 else f"cat{i % categories}"
        source = SOURCES[0] if skew and i % 7 else SOURCES[i % 3]
        band = ["exact_identifier", "high", "medium", "low"][0 if skew and i % 5 else i % 4]
        items.append(Candidate(uuid.UUID(int=10_000 + i), category, source, band))
    return items


def test_sample_of_1000_covers_every_category_source_and_band() -> None:
    population = _population(1_000)
    sample = stratified_sample(population, size=200, seed=7)
    assert len(sample) == 200
    assert len({c.match_version_id for c in sample}) == 200
    for attribute in ("category", "source_id", "band"):
        assert {getattr(c, attribute) for c in sample} == {
            getattr(c, attribute) for c in population
        }


def test_sample_is_reproducible_and_seed_dependent() -> None:
    population = _population(1_000)
    first = stratified_sample(population, size=200, seed=42)
    assert first == stratified_sample(list(reversed(population)), size=200, seed=42)
    assert first != stratified_sample(population, size=200, seed=43)


def test_small_population_is_audited_completely() -> None:
    population = _population(57)
    assert sorted(stratified_sample(population, size=200, seed=1), key=str) == sorted(
        population, key=str
    )
    assert stratified_sample([], size=200, seed=1) == []


def test_allocation_follows_stratum_sizes() -> None:
    population = _population(1_000, skew=False)
    counts = Counter(c.category for c in stratified_sample(population, size=200, seed=3))
    assert all(45 <= n <= 55 for n in counts.values())  # 4 equal categories → about 50 each


@settings(max_examples=50, deadline=None)
@given(n=st.integers(1, 400), size=st.integers(1, 250), seed=st.integers(0, 2**32))
def test_sample_size_and_coverage_invariants(n: int, size: int, seed: int) -> None:
    population = _population(n)
    sample = stratified_sample(population, size=size, seed=seed)
    assert len(sample) == min(size, n)
    assert len(set(sample)) == len(sample)
    values = set().union(*(c.values() for c in population))
    if size >= len(values):
        assert set().union(*(c.values() for c in sample)) == values


def test_confidence_bands() -> None:
    assert confidence_band(10_000, exact=True) == "exact_identifier"
    assert [confidence_band(v, exact=False) for v in (9_500, 8_500, 7_000)] == [
        "high",
        "medium",
        "low",
    ]


def test_percentile_is_nearest_rank() -> None:
    assert percentile(list(range(1, 11)), 90) == 9
    assert percentile([5.0], 90) == 5
    assert percentile([], 90) is None


def _category(
    name: str, decisions: int, median_minutes: float, baseline_minutes: float | None
) -> CategoryReviewTime:
    return CategoryReviewTime(
        category=name,
        decisions=decisions,
        median_seconds=median_minutes * 60,
        p90_seconds=None,
        baseline_seconds=round(baseline_minutes * 60) if baseline_minutes else None,
        low_sample=decisions < 30,
    )


def test_reduction_against_baseline() -> None:
    baseline, measured, reduction = weighted_reduction([_category("ssd", 40, 2.5, 6)])
    assert (baseline, measured) == (360, 150)
    assert reduction is not None
    assert round(reduction) == 58


def test_reduction_on_the_category_mix() -> None:
    baseline, measured, reduction = weighted_reduction(
        [_category("gpu", 50, 3, 8), _category("ssd", 50, 2, 4), _category("ram", 9, 1, None)]
    )
    assert baseline == pytest.approx(6 * 60)
    assert measured == pytest.approx(2.5 * 60)
    assert reduction is not None
    assert round(reduction) == 58
    assert weighted_reduction([_category("ram", 9, 1, None)]) == (None, None, None)
