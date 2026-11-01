import pytest
from hypothesis import given
from hypothesis import strategies as st

from pricing_assistant.core.money import (
    CurrencyUnit,
    MoneyParseError,
    parse_amount,
    parse_currency_unit,
    parse_to_rial,
    rial_to_toman,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("۸٬۴۰۰٬۰۰۰", 8_400_000),
        ("8,400,000", 8_400_000),
        ("٨٤٠٠٠٠٠", 8_400_000),
        ("8 400 000", 8_400_000),
        ("۸۴۰۰۰۰۰", 8_400_000),
        ("8400000.00", 8_400_000),
        (" 12 ", 12),
        (0, 0),
        (75, 75),
    ],
)
def test_parse_amount_accepts_persian_arabic_and_latin_forms(
    text: str | int, expected: int
) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "-5", "8.5", "۸٫۵", "1e6", "12,5a", True])
def test_parse_amount_rejects_invalid_values(text: str | bool) -> None:
    with pytest.raises(MoneyParseError):
        parse_amount(text)


def test_toman_is_converted_to_rial() -> None:
    assert parse_to_rial("۸٬۴۰۰٬۰۰۰", CurrencyUnit.TOMAN) == 84_000_000
    assert parse_to_rial("8,400,000", CurrencyUnit.RIAL) == 8_400_000


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("TOMAN", CurrencyUnit.TOMAN),
        ("toman", CurrencyUnit.TOMAN),
        ("تومان", CurrencyUnit.TOMAN),
        ("IRT", CurrencyUnit.TOMAN),
        ("RIAL", CurrencyUnit.RIAL),
        ("ریال", CurrencyUnit.RIAL),
        ("IRR", CurrencyUnit.RIAL),
    ],
)
def test_currency_unit_aliases(text: str, unit: CurrencyUnit) -> None:
    assert parse_currency_unit(text) is unit


def test_missing_unit_is_none_and_unknown_unit_is_an_error() -> None:
    assert parse_currency_unit(None) is None
    assert parse_currency_unit("  ") is None
    with pytest.raises(MoneyParseError):
        parse_currency_unit("USD")


@given(st.integers(min_value=0, max_value=10**15))
def test_toman_rial_round_trip(amount: int) -> None:
    assert rial_to_toman(parse_to_rial(f"{amount:,}", CurrencyUnit.TOMAN)) == amount
