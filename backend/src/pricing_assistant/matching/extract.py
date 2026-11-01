"""Rule-based attribute extraction from offer titles and seller conditions (D8 step 2, task 7.3).

Every attribute keeps its provenance: ``structured_data`` (page markup), ``rule`` (these
dictionaries and patterns), later ``llm`` or ``human``. Brands, warranty providers and sale
conditions come from static Persian/English dictionaries; models come from the tenant's own
catalog (the models we sell) plus generic GPU/RAM model patterns.
"""

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pricing_assistant.matching.models import AttributeSource
from pricing_assistant.matching.normalize import normalize_key, normalize_persian, normalize_title

IDENTITY_FIELDS = ("brand", "model", "capacity", "generation", "frequency", "colour_edition")
CONDITION_FIELDS = ("warranty_provider", "warranty_months", "condition", "payment")
IDENTIFIER_FIELDS = ("mpn", "gtin")

BRANDS: dict[str, tuple[str, ...]] = {
    "Samsung": ("samsung", "سامسونگ"),
    "Western Digital": ("western digital", "wd", "وسترن دیجیتال", "وسترن"),
    "Kingston": ("kingston", "کینگستون"),
    "Crucial": ("crucial", "کروشیال"),
    "ADATA": ("adata", "ای دیتا", "ای‌دیتا"),
    "Lexar": ("lexar", "لکسار"),
    "Transcend": ("transcend", "ترنسند"),
    "Seagate": ("seagate", "سیگیت"),
    "ASUS": ("asus", "ایسوس", "ایسوز"),
    "MSI": ("msi", "ام اس آی"),
    "Gigabyte": ("gigabyte", "گیگابایت"),
    "Zotac": ("zotac", "زوتک"),
    "Palit": ("palit", "پالیت"),
    "Sapphire": ("sapphire", "سافایر"),
    "PowerColor": ("powercolor", "پاورکالر"),
    "Corsair": ("corsair", "کورسیر"),
    "G.Skill": ("g.skill", "gskill", "جی اسکیل"),
    "TeamGroup": ("teamgroup", "team group", "تیم گروپ"),
    "Intel": ("intel", "اینتل"),
    "AMD": ("amd", "ای ام دی"),
}
WARRANTY_PROVIDERS: dict[str, tuple[str, ...]] = {
    "آواژنگ": ("آواژنگ", "avajang"),
    "ماتریس": ("ماتریس", "matrix"),
    "سازگار ارقام": ("سازگار ارقام", "سازگار"),
    "حامی": ("حامی", "hami"),
    "اسپادان": ("اسپادان",),
    "پارس": ("پارس",),
    "آسان سرویس": ("آسان سرویس",),
    "گرین": ("گرین",),
}
_CONDITIONS = (
    ("open_box", ("جعبه باز", "اوپن باکس", "open box", "openbox")),
    ("used", ("کارکرده", "دست دوم", "استوک", "used", "refurbished", "ریفربیش")),
    ("new", ("آکبند", "نو ", "new", "sealed", "اورجینال نو")),
)
_INSTALMENT = ("اقساطی", "قسطی", "اقساط", "instalment", "installment")
_COLOURS = {
    "black": ("مشکی", "black"),
    "white": ("سفید", "white"),
    "silver": ("نقره ای", "نقره‌ای", "silver"),
    "rgb": ("rgb",),
}
_EDITIONS = {
    "heatsink": ("هیت سینک", "هیتسینک", "heatsink", "heat sink"),
    "oc": (" oc", "o8g", "o16g", "overclock"),
}
_CAPACITY = re.compile(r"(\d+(?:\.\d+)?)\s?(TB|GB)\b")
_GENERATION = (
    re.compile(r"\bgen\s?(\d)\b"),
    re.compile(r"\bpcie\s?(\d)(?:\.0)?\b"),
    re.compile(r"نسل\s?(\d)"),
)
_DDR = re.compile(r"\bddr(\d)\b")
_FREQUENCY = (re.compile(r"\b(\d{4,5})\s?MHz\b"), re.compile(r"\bddr\d\s?(\d{4})\b"))
_GPU_MODEL = re.compile(r"\b(rtx|gtx|rx|arc)\s?(\d{3,4})(?:\s?(ti|super|xtx|xt))?\b")
_WARRANTY_MONTHS = (
    re.compile(r"(\d{1,2})\s?ماه(?:ه)?"),
    re.compile(r"(\d{1,2})\s?months?\b"),
)
_WARRANTY_YEARS = (re.compile(r"(\d)\s?سال(?:ه)?"), re.compile(r"(\d)\s?years?\b"))
_MPN_IN_TITLE = re.compile(r"\b([A-Z0-9]{2,6}-[A-Z0-9]{4,12}(?:-[A-Z0-9]{2,8})?)\b")


@dataclass(frozen=True, slots=True)
class Attr:
    value: str | int
    source: AttributeSource

    def as_json(self) -> dict[str, Any]:
        return {"value": self.value, "source": self.source.value}


Attributes = dict[str, Attr]


def model_key(model: str) -> str:
    """Comparison key for models: normalized, no spaces or punctuation."""
    return re.sub(r"[\s\-_.]", "", normalize_title(model)).lower()


def _find_alias(text: str, table: Mapping[str, Iterable[str]]) -> str | None:
    best: tuple[int, str] | None = None
    for canonical, aliases in table.items():
        for alias in aliases:
            alias_n = normalize_title(alias)
            pattern = rf"(?<![\w]){re.escape(alias_n)}(?![\w])"
            if re.search(pattern, text, re.IGNORECASE) and (best is None or len(alias_n) > best[0]):
                best = (len(alias_n), canonical)
    return best[1] if best else None


def _model(text: str, known_models: Iterable[str]) -> str | None:
    squashed = re.sub(r"[\s\-_.]", "", text).lower()
    best: str | None = None
    for model in known_models:
        key = model_key(model)
        if key and key in squashed and (best is None or len(key) > len(model_key(best))):
            best = model
    if best is not None:
        return best
    gpu = _GPU_MODEL.search(text)
    if gpu:
        suffix = (
            f" {gpu.group(3).upper() if gpu.group(3) != 'ti' else 'Ti'}" if gpu.group(3) else ""
        )
        return f"{gpu.group(1).upper()} {gpu.group(2)}{suffix}"
    return None


def _capacity(text: str) -> str | None:
    match = _CAPACITY.search(text)
    if not match:
        return None
    number = match.group(1).rstrip("0").rstrip(".") if "." in match.group(1) else match.group(1)
    return f"{number}{match.group(2)}"


def _generation(text: str) -> str | None:
    for pattern in _GENERATION:
        if match := pattern.search(text):
            return f"gen{match.group(1)}"
    if match := _DDR.search(text):
        return f"ddr{match.group(1)}"
    return None


_BARE_RAM_SPEED = re.compile(r"(?<![\d.])(1[6-9]\d\d|[2-9]\d{3})(?![\d.]|\s?(?:GB|TB|MB))")


def _frequency(text: str) -> str | None:
    for pattern in _FREQUENCY:
        if match := pattern.search(text):
            return f"{match.group(1)}MHz"
    # Memory listings often state the speed as a bare number: «DDR5 · 32GB / 5600».
    if _DDR.search(text) and (match := _BARE_RAM_SPEED.search(_DDR.sub(" ", text))):
        return f"{match.group(1)}MHz"
    return None


def _flag_terms(text: str, table: Mapping[str, Iterable[str]]) -> list[str]:
    padded = f" {text} "
    return sorted(
        name
        for name, terms in table.items()
        if any(normalize_title(t) in padded or t in padded for t in terms)
    )


def _warranty_months(text: str) -> int | None:
    for pattern in _WARRANTY_MONTHS:
        if match := pattern.search(text):
            return int(match.group(1))
    if "گارانتی" not in text and "warranty" not in text:
        return None
    for pattern in _WARRANTY_YEARS:
        if match := pattern.search(text):
            return int(match.group(1)) * 12
    return None


def _condition(text: str) -> str:
    padded = f" {text} "
    for name, terms in _CONDITIONS:
        if any(normalize_title(t) in padded for t in terms):
            return name
    return "new"


def extract(
    title: str | None,
    *,
    conditions: Mapping[str, Any] | None = None,
    identifiers: Mapping[str, Any] | None = None,
    known_models: Iterable[str] = (),
) -> Attributes:
    """Normalized attributes of one market offer."""
    conditions = conditions or {}
    identifiers = identifiers or {}
    text = normalize_title(title or "")
    cond_text = normalize_title(" ".join(str(v) for v in conditions.values() if v))
    rule = AttributeSource.RULE
    attrs: Attributes = {}

    if brand := _find_alias(text, BRANDS):
        attrs["brand"] = Attr(brand, rule)
    if model := _model(text, known_models):
        attrs["model"] = Attr(model, rule)
    if capacity := _capacity(text):
        attrs["capacity"] = Attr(capacity, rule)
    if generation := _generation(text):
        attrs["generation"] = Attr(generation, rule)
    if frequency := _frequency(text):
        attrs["frequency"] = Attr(frequency, rule)
    edition = _flag_terms(text, _EDITIONS) + _flag_terms(text, _COLOURS)
    if edition:
        attrs["colour_edition"] = Attr("+".join(edition), rule)

    warranty_text = f"{cond_text} {text}"
    if provider := _find_alias(warranty_text, WARRANTY_PROVIDERS):
        attrs["warranty_provider"] = Attr(provider, rule)
    if (months := _warranty_months(warranty_text)) is not None:
        attrs["warranty_months"] = Attr(months, rule)
    attrs["condition"] = Attr(_condition(f"{cond_text} {text}"), rule)
    payment = "instalment" if any(t in f"{cond_text} {text}" for t in _INSTALMENT) else "cash"
    attrs["payment"] = Attr(payment, rule)

    for key in ("gtin", "gtin13", "gtin14", "gtin12", "gtin8"):
        if identifiers.get(key):
            attrs["gtin"] = Attr(
                re.sub(r"\D", "", str(identifiers[key])), AttributeSource.STRUCTURED_DATA
            )
            break
    if identifiers.get("mpn"):
        attrs["mpn"] = Attr(
            str(identifiers["mpn"]).strip().upper(), AttributeSource.STRUCTURED_DATA
        )
    elif mpn := _MPN_IN_TITLE.search(normalize_persian(title or "")):
        attrs["mpn"] = Attr(mpn.group(1).upper(), rule)
    return attrs


LLM_FIELDS = (*IDENTITY_FIELDS, "warranty_provider", "warranty_months")


def merge_llm(
    attrs: Attributes, extracted: Mapping[str, Any], *, known_models: Iterable[str] = ()
) -> Attributes:
    """Fill attributes the rules could not find with validated LLM values (D8 step 3).

    Rule and structured-data values always win; the LLM only fills gaps. Brand and model are
    mapped onto the same canonical names the rules use when they are recognisable.
    """
    merged = dict(attrs)
    for name in LLM_FIELDS:
        value = extracted.get(name)
        if name in merged or value is None or value == "":
            continue
        if name == "brand":
            value = _find_alias(normalize_title(str(value)), BRANDS) or str(value).strip()
        elif name == "model":
            value = _model(normalize_title(str(value)), known_models) or str(value).strip()
        merged[name] = Attr(value, AttributeSource.LLM)
    return merged


def rule_part(attrs: Mapping[str, Any]) -> dict[str, Any]:
    """The stored attributes (JSON form) without LLM-derived values."""
    return {k: v for k, v in attrs.items() if v["source"] != AttributeSource.LLM.value}


def to_json(attrs: Attributes) -> dict[str, Any]:
    return {key: attr.as_json() for key, attr in sorted(attrs.items())}


def from_json(data: Mapping[str, Any]) -> Attributes:
    return {key: Attr(v["value"], AttributeSource(v["source"])) for key, v in data.items()}


def attributes_hash(attrs: Attributes) -> str:
    """Hash of values only (not provenance): re-extraction by another method keeps the hash."""
    values = {key: attrs[key].value for key in sorted(attrs)}
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def seller_key(seller: str | None) -> str:
    return normalize_key(seller)
