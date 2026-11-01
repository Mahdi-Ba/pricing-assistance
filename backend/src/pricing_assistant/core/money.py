"""Money parsing and currency normalisation.

All amounts are stored as integer Rial. Inputs may use Persian (۰-۹) or Arabic-Indic (٠-٩)
digits and Latin, Arabic (٬) or Persian thousands separators. Conversion happens once, at the
ingestion boundary; nothing downstream sees Toman.
"""

import re
from enum import StrEnum

RIAL_PER_TOMAN = 10

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# Thousands separators: comma, Arabic thousands separator, Arabic comma, apostrophe, spaces.
_SEPARATORS = re.compile(r"[,\u066c\u060c'\u2019\s\u00a0\u202f\u200c]")
_INTEGER = re.compile(r"^\d+$")
_TRAILING_ZERO_DECIMAL = re.compile(r"^(\d+)[.٫]0+$")


class CurrencyUnit(StrEnum):
    RIAL = "RIAL"
    TOMAN = "TOMAN"


_UNIT_ALIASES = {
    "rial": CurrencyUnit.RIAL,
    "irr": CurrencyUnit.RIAL,
    "ریال": CurrencyUnit.RIAL,
    "toman": CurrencyUnit.TOMAN,
    "irt": CurrencyUnit.TOMAN,
    "تومان": CurrencyUnit.TOMAN,
}


class MoneyParseError(ValueError):
    """The text is not a valid non-negative whole amount."""


def normalize_digits(text: str) -> str:
    return text.translate(_DIGITS)


def parse_currency_unit(text: str | None) -> CurrencyUnit | None:
    if text is None:
        return None
    key = normalize_digits(text).strip().lower()
    if not key:
        return None
    unit = _UNIT_ALIASES.get(key)
    if unit is None:
        raise MoneyParseError(f"unknown currency unit: {text!r}")
    return unit


def parse_amount(text: str | int) -> int:
    """Parse a non-negative whole amount in its source unit. Rejects fractions and negatives."""
    if isinstance(text, bool):
        raise MoneyParseError("boolean is not an amount")
    if isinstance(text, int):
        if text < 0:
            raise MoneyParseError("amount must not be negative")
        return text
    cleaned = _SEPARATORS.sub("", normalize_digits(text))
    if match := _TRAILING_ZERO_DECIMAL.fullmatch(cleaned):
        cleaned = match.group(1)
    if not _INTEGER.fullmatch(cleaned):
        raise MoneyParseError(f"not a whole non-negative amount: {text!r}")
    return int(cleaned)


def to_rial(amount: int, unit: CurrencyUnit) -> int:
    if amount < 0:
        raise MoneyParseError("amount must not be negative")
    return amount * RIAL_PER_TOMAN if unit is CurrencyUnit.TOMAN else amount


def parse_to_rial(text: str | int, unit: CurrencyUnit) -> int:
    return to_rial(parse_amount(text), unit)


def rial_to_toman(amount_rial: int) -> int:
    """Whole Toman for display; amounts below one Toman are truncated."""
    return amount_rial // RIAL_PER_TOMAN
