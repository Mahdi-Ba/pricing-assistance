"""Prometheus metrics for collection (design D13)."""

from prometheus_client import Counter, Histogram

FETCH_OUTCOMES = Counter(
    "pa_fetch_outcomes_total",
    "Fetch attempts by source and result",
    ["source", "outcome", "error_class"],
)
OBSERVATIONS = Counter("pa_observations_total", "Stored observations by validity", ["validity"])
DATA_AGE_SECONDS = Histogram(
    "pa_observation_data_age_seconds",
    "Age of the newest valid observation per tracked offer when evaluated",
    buckets=(300, 900, 1800, 3600, 7200, 14400, 43200, 86400, 172800),
)
