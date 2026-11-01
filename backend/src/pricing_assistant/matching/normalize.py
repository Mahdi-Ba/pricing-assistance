"""Text normalization for Persian/English product titles (design D8 step 1, task 7.2).

- Arabic letters → Persian (ي→ی, ك→ک, ة→ه, أ/إ/آ kept as-is except hamza variants → ا)
- Persian and Arabic-Indic digits → ASCII
- ZWNJ and other zero-width characters → space; tatweel removed
- Persian unit words → canonical Latin units (ترابایت→TB, گیگابایت→GB, مگاهرتز→MHz, ...)
- Latin text lower-cased, separators and whitespace collapsed
"""

import re

from pricing_assistant.core.text import normalize_key, normalize_persian

__all__ = ["normalize_key", "normalize_persian", "normalize_title"]

_SEPARATORS = re.compile(r"[\s\u00a0،,؛;|/\\()\[\]{}«»\"'“”‘’_+]+")

# Order matters: longer phrases first. Values are canonical tokens.
_UNIT_SYNONYMS: tuple[tuple[str, str], ...] = (
    (r"ترا\s*بایت|ترابایت|ترا|tera\s*bytes?|terabytes?|tb", "TB"),
    (r"گیگا\s*بایت|گیگابایت|گیگ|giga\s*bytes?|gigabytes?|gb", "GB"),
    (r"مگا\s*بایت|مگابایت|megabytes?|mb", "MB"),
    (r"مگا\s*هرتز|مگاهرتز|mhz", "MHz"),
    (r"گیگا\s*هرتز|گیگاهرتز|ghz", "GHz"),
)
_UNIT_PATTERNS = [
    (re.compile(rf"(?<=\d)\s*(?:{p})\b|\b(?:{p})\b", re.IGNORECASE), t) for p, t in _UNIT_SYNONYMS
]
_NUMBER_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s+(TB|GB|MB|MHz|GHz)\b")


def normalize_title(text: str) -> str:
    """Canonical form used for attribute extraction and comparison."""
    text = normalize_persian(text)
    for pattern, token in _UNIT_PATTERNS:
        text = pattern.sub(f" {token}", text)
    text = _SEPARATORS.sub(" ", text)
    text = re.sub(
        r"[A-Za-z]+",
        lambda m: (
            m.group(0) if m.group(0) in {"TB", "GB", "MB", "MHz", "GHz"} else m.group(0).lower()
        ),
        text,
    )
    text = _NUMBER_UNIT.sub(r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()
