"""Stratified match-audit sampling and small statistics helpers (tasks 13.1, 13.3, 13.4).

Pure and seeded: the same population and seed always give the same sample, so a stored sample
can be re-derived and checked.

Allocation (``size`` = min(target, population)):

1. Coverage: every category, every source and every confidence band present in the population
   gets at least one sampled match. Greedy: repeatedly pick the match that covers the most
   still-uncovered values (random among ties).
2. The rest is allocated to the full strata (category × source × band) in proportion to their
   population (largest remainder), and drawn at random within each stratum.
"""

import math
import random
import statistics
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_SAMPLE_SIZE = 200


@dataclass(frozen=True, slots=True)
class Candidate:
    match_version_id: uuid.UUID
    category: str
    source_id: uuid.UUID
    band: str

    @property
    def stratum(self) -> tuple[str, uuid.UUID, str]:
        return (self.category, self.source_id, self.band)

    def values(self) -> set[tuple[str, object]]:
        return {("category", self.category), ("source", self.source_id), ("band", self.band)}


def confidence_band(confidence_bp: int, *, exact: bool) -> str:
    """Bands of the confidence the match was *proposed* with."""
    if exact:
        return "exact_identifier"
    if confidence_bp >= 9_000:  # noqa: PLR2004 - band edges
        return "high"
    if confidence_bp >= 8_000:  # noqa: PLR2004
        return "medium"
    return "low"


def stratified_sample(
    population: Sequence[Candidate], *, size: int = DEFAULT_SAMPLE_SIZE, seed: int
) -> list[Candidate]:
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    pool = sorted(population, key=lambda c: str(c.match_version_id))
    rng.shuffle(pool)
    size = min(size, len(pool))
    chosen: list[Candidate] = []
    chosen_ids: set[uuid.UUID] = set()

    uncovered = set().union(*(c.values() for c in pool)) if pool else set()
    while uncovered and len(chosen) < size:
        _, best = max(
            enumerate(pool), key=lambda pair: (len(pair[1].values() & uncovered), -pair[0])
        )
        if not best.values() & uncovered:
            break
        chosen.append(best)
        chosen_ids.add(best.match_version_id)
        uncovered -= best.values()

    remaining = size - len(chosen)
    if remaining > 0:
        strata: dict[tuple[str, uuid.UUID, str], list[Candidate]] = defaultdict(list)
        for c in pool:
            if c.match_version_id not in chosen_ids:
                strata[c.stratum].append(c)
        total = sum(len(v) for v in strata.values())
        quotas = {k: remaining * len(v) / total for k, v in strata.items()}
        allocation = {k: math.floor(q) for k, q in quotas.items()}
        leftover = remaining - sum(allocation.values())
        for key in sorted(quotas, key=lambda k: (quotas[k] - allocation[k], str(k)), reverse=True)[
            :leftover
        ]:
            allocation[key] += 1
        for key, members in sorted(strata.items(), key=lambda kv: str(kv[0])):
            chosen.extend(members[: allocation[key]])
    return chosen


# --- statistics ----------------------------------------------------------------------------------


def median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Nearest-rank percentile (p90 of 10 values is the 9th smallest)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return float(ordered[rank - 1])


def share(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 2) if whole else None
