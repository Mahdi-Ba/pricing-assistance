from datetime import UTC, date, datetime

import pytest

from pricing_assistant.core.persian import jalali_datetime, percent_bp, to_jalali, toman


@pytest.mark.parametrize(
    ("gregorian", "jalali"),
    [
        (date(2026, 10, 25), (1405, 8, 3)),
        (date(2025, 3, 21), (1404, 1, 1)),  # Nowruz 1404
        (date(2024, 3, 20), (1403, 1, 1)),  # Nowruz 1403
        (date(2023, 3, 20), (1401, 12, 29)),
        (date(2000, 1, 1), (1378, 10, 11)),
        (date(2026, 3, 20), (1404, 12, 29)),
    ],
)
def test_to_jalali(gregorian: date, jalali: tuple[int, int, int]) -> None:
    assert to_jalali(gregorian) == jalali


def test_toman_and_percent() -> None:
    assert toman(86_000_000) == "۸٬۶۰۰٬۰۰۰ تومان"
    assert percent_bp(1_000) == "۱۰٪"
    assert percent_bp(150) == "۱٫۵٪"


def test_jalali_datetime_uses_tehran_time() -> None:
    assert jalali_datetime(datetime(2026, 10, 25, 8, 30, tzinfo=UTC)) == "۳ آبان ۱۴۰۵، ۱۲:۰۰"
