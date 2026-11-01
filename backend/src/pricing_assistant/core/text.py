"""Persian text normalization shared by all modules (letters, digits, invisible characters)."""

import re
import unicodedata

_LETTERS = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "أ": "ا",
        "إ": "ا",
        "ٱ": "ا",
        "ؤ": "و",
        "ـ": "",  # tatweel
    }
)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ZERO_WIDTH = re.compile(r"[\u200c\u200d\u200e\u200f\u2060\ufeff]")
_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670]")


def normalize_persian(text: str) -> str:
    """Letters, digits and invisible characters only; keeps the original words and case."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_LETTERS).translate(_DIGITS)
    text = _DIACRITICS.sub("", text)
    return _ZERO_WIDTH.sub(" ", text)


def normalize_key(text: str | None) -> str:
    """Comparison key for short values (seller names, warranty providers): no case, no spaces."""
    if not text:
        return ""
    return re.sub(r"[\s\-_.]+", "", normalize_persian(text)).lower()
