"""Output checks beyond the JSON schema (tasks 8.4, 8.5)."""

import re
from collections import Counter
from decimal import Decimal

_DIGITS = "0-9۰-۹٠-٩"
_NUMBER = re.compile(rf"[{_DIGITS}]+(?:[,٬][{_DIGITS}]{{3}})*(?:[.٫][{_DIGITS}]+)?")
_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def numbers(text: str) -> Counter[str]:
    """Multiset of the numeric values in ``text`` (Persian, Arabic-Indic or ASCII digits).

    Thousands separators (``,`` ``٬``) are dropped, decimal separators (``.`` ``٫``) become ``.``
    and leading zeros are ignored, so ``۸٬۴۰۰٬۰۰۰``, ``8,400,000`` and ``8400000`` are equal.
    """
    found: Counter[str] = Counter()
    for token in _NUMBER.findall(text):
        ascii_token = token.translate(_TO_ASCII).replace(",", "").replace("٬", "")
        value = Decimal(ascii_token.replace("٫", "."))
        found[format(value.normalize(), "f")] += 1
    return found


def numbers_preserved(original: str, rephrased: str) -> bool:
    """True when the rephrased text has exactly the original's numbers, no more and no fewer."""
    return numbers(original) == numbers(rephrased)
