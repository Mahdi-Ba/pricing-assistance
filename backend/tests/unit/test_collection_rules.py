import random

import pytest

from pricing_assistant.collection.fetching import BACKOFF_BASE_MS, backoff_ms, plausibility
from pricing_assistant.collection.models import Validity


@pytest.mark.parametrize(
    ("price", "previous", "expected"),
    [
        (86_000_000, 86_000_000, Validity.VALID),
        (8_600_000, 86_000_000, Validity.SUSPECT_UNIT),  # Toman read as Rial
        (860_000_000, 86_000_000, Validity.SUSPECT_UNIT),  # Rial read as Toman
        (17_200_000, 86_000_000, Validity.VALID),  # exactly 0.2×
        (430_000_000, 86_000_000, Validity.VALID),  # exactly 5×
        (86_000_000, None, Validity.VALID),
        (None, 86_000_000, Validity.VALID),
    ],
)
def test_plausibility_band(price: int | None, previous: int | None, expected: Validity) -> None:
    assert plausibility(price, previous) is expected


def test_backoff_is_exponential_with_bounded_jitter() -> None:
    rng = random.Random(7)
    for attempt in (1, 2, 3):
        delay = backoff_ms(attempt, rng=rng)
        base = BACKOFF_BASE_MS * 2 ** (attempt - 1)
        assert base <= delay <= base + BACKOFF_BASE_MS
