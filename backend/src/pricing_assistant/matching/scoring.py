"""Candidate blocking, weighted scoring and match-state assignment (D8 steps 4–7, tasks 7.4/7.5).

Pure functions: same attributes in, same assessment out.

- Identity attributes (brand, model, capacity, generation, frequency, colour/edition) decide
  whether it is the same product. A disagreement on any of them is fatal (``identity_mismatch``).
- Sale conditions (warranty, condition, payment) decide whether the offer is *equivalent*. A
  disagreement is ``condition_mismatch`` and always needs an expert.
- Auto-confirmation only on an equal, valid identifier (MPN, or GTIN with a correct check digit)
  with every identity attribute and sale condition equal, and no attribute taken from the LLM.
  LLM proposals are never confirmed.
"""

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pricing_assistant.matching.extract import Attributes, model_key
from pricing_assistant.matching.models import AttributeSource, DecisionSource, MatchState

WEIGHTS: dict[str, int] = {
    "brand": 2,
    "model": 4,
    "capacity": 3,
    "generation": 2,
    "frequency": 1,
    "colour_edition": 1,
}
REQUIRED_FOR_MATCH = ("brand", "model")
PROPOSE_THRESHOLD_BP = 8_000
BP = 10_000


@dataclass(frozen=True, slots=True)
class VariantProfile:
    """Our variant's identity and sale conditions (new, cash, our warranty)."""

    id: uuid.UUID
    brand: str
    model: str
    mpn: str | None = None
    gtin: str | None = None
    capacity: str | None = None
    generation: str | None = None
    frequency: str | None = None
    colour_edition: str | None = None
    warranty_provider: str | None = None
    warranty_months: int | None = None

    def identity(self) -> dict[str, str]:
        return {
            k: v
            for k, v in (
                ("brand", self.brand),
                ("model", self.model),
                ("capacity", self.capacity),
                ("generation", self.generation),
                ("frequency", self.frequency),
                ("colour_edition", self.colour_edition),
            )
            if v
        }


@dataclass(frozen=True, slots=True)
class Assessment:
    variant_id: uuid.UUID
    state: MatchState
    confidence_bp: int
    flags: list[str] = field(default_factory=list)
    decided_by: DecisionSource = DecisionSource.RULE

    @property
    def is_auto_confirmed(self) -> bool:
        return self.state is MatchState.CONFIRMED


def gtin_valid(gtin: str | None) -> bool:
    """GS1 check digit for GTIN-8/12/13/14."""
    if not gtin or not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", gtin):
        return False
    digits = [int(d) for d in gtin]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


_NUMERIC_FIELDS = ("frequency", "generation")  # "5600MHz" = "5600", "ddr5" = "gen 5" = "5"


def _norm(field_name: str, value: object) -> str:
    text = str(value)
    if field_name == "model":
        return model_key(text)
    if field_name in _NUMERIC_FIELDS and (digits := re.sub(r"\D", "", text)):
        return digits
    return re.sub(r"\s+", "", text).lower()


def _mpn_key(value: str | None) -> str:
    return re.sub(r"[\s\-_.]", "", value or "").upper()


def _condition_flags(offer: Attributes, variant: VariantProfile) -> list[str]:
    flags: list[str] = []
    provider = offer.get("warranty_provider")
    months = offer.get("warranty_months")
    if (
        provider is not None
        and variant.warranty_provider
        and _norm("p", provider.value) != _norm("p", variant.warranty_provider)
    ) or (
        months is not None
        and variant.warranty_months is not None
        and int(months.value) != variant.warranty_months
    ):
        flags.append("condition_mismatch:warranty")
    condition = offer.get("condition")
    if condition is not None and condition.value != "new":
        flags.append("condition_mismatch:condition")
    payment = offer.get("payment")
    if payment is not None and payment.value != "cash":
        flags.append("condition_mismatch:payment")
    return flags


def _identifier_match(offer: Attributes, variant: VariantProfile) -> bool:
    mpn = offer.get("mpn")
    if mpn is not None and variant.mpn and _mpn_key(str(mpn.value)) == _mpn_key(variant.mpn):
        return True
    gtin = offer.get("gtin")
    return (
        gtin is not None
        and variant.gtin is not None
        and gtin_valid(str(gtin.value))
        and gtin_valid(variant.gtin)
        and str(gtin.value) == variant.gtin
    )


def _fully_equal(offer: Attributes, variant: VariantProfile) -> bool:
    """Every identity attribute we know must be present on the offer and equal; the warranty
    must be known on both sides and equal (provider and duration)."""
    for name, ours in variant.identity().items():
        theirs = offer.get(name)
        if theirs is None or _norm(name, theirs.value) != _norm(name, ours):
            return False
    provider, months = offer.get("warranty_provider"), offer.get("warranty_months")
    return (
        variant.warranty_provider is not None
        and variant.warranty_months is not None
        and provider is not None
        and months is not None
        and _norm("p", provider.value) == _norm("p", variant.warranty_provider)
        and int(months.value) == variant.warranty_months
    )


@dataclass(frozen=True, slots=True)
class AttributeComparison:
    """One row of the side-by-side view (review-workspace: Side-by-side compare)."""

    name: str
    ours: str | int | None
    theirs: str | int | None
    source: str | None  # provenance of the offer's value
    state: str  # equal | different | missing_offer | missing_ours


COMPARED = (
    "brand",
    "model",
    "capacity",
    "generation",
    "frequency",
    "colour_edition",
    "warranty_provider",
    "warranty_months",
    "condition",
    "payment",
    "mpn",
    "gtin",
)
_OURS_FIXED: dict[str, str] = {"condition": "new", "payment": "cash"}  # what we sell


def compare(offer: Attributes, variant: VariantProfile) -> list[AttributeComparison]:
    """Normalized attributes of our variant and the offer, with a state per attribute."""
    ours_by_name: dict[str, str | int | None] = {
        **variant.identity(),
        "warranty_provider": variant.warranty_provider,
        "warranty_months": variant.warranty_months,
        "mpn": variant.mpn,
        "gtin": variant.gtin,
        **_OURS_FIXED,
    }
    rows = []
    for name in COMPARED:
        ours = ours_by_name.get(name)
        attr = offer.get(name)
        theirs = attr.value if attr is not None else None
        if ours is None and theirs is None:
            continue
        if theirs is None:
            state = "missing_offer"
        elif ours is None:
            state = "missing_ours"
        elif name == "mpn":
            state = "equal" if _mpn_key(str(theirs)) == _mpn_key(str(ours)) else "different"
        else:
            state = "equal" if _norm(name, theirs) == _norm(name, ours) else "different"
        rows.append(
            AttributeComparison(
                name=name,
                ours=ours,
                theirs=theirs,
                source=attr.source.value if attr is not None else None,
                state=state,
            )
        )
    return rows


def assess(
    offer: Attributes, variant: VariantProfile, *, proposed_by: DecisionSource = DecisionSource.RULE
) -> Assessment:
    flags: list[str] = []
    agree = present = 0
    for name, weight in WEIGHTS.items():
        theirs, ours = offer.get(name), variant.identity().get(name)
        if theirs is None or ours is None:
            continue
        present += weight
        if _norm(name, theirs.value) == _norm(name, ours):
            agree += weight
        else:
            flags.append(f"identity_mismatch:{name}")
    missing = [f"missing:{name}" for name in REQUIRED_FOR_MATCH if name not in offer]
    confidence = (agree * BP // present) if present else 0
    condition_flags = _condition_flags(offer, variant)
    flags += missing + condition_flags

    if any(f.startswith("identity_mismatch") for f in flags):
        return Assessment(
            variant.id, MatchState.NEEDS_REVIEW, min(confidence, 4_000), flags, proposed_by
        )
    if (
        proposed_by is DecisionSource.RULE
        and not flags
        and not any(a.source is AttributeSource.LLM for a in offer.values())
        and _identifier_match(offer, variant)
        and _fully_equal(offer, variant)
    ):
        return Assessment(variant.id, MatchState.CONFIRMED, BP, [], DecisionSource.RULE)
    if condition_flags or missing or confidence < PROPOSE_THRESHOLD_BP:
        return Assessment(variant.id, MatchState.NEEDS_REVIEW, confidence, flags, proposed_by)
    return Assessment(variant.id, MatchState.PROPOSED, confidence, flags, proposed_by)


def block_candidates(offer: Attributes, variants: Iterable[VariantProfile]) -> list[VariantProfile]:
    """Variants worth scoring: same brand (when known) and same model family."""
    brand, model = offer.get("brand"), offer.get("model")
    result = []
    for variant in variants:
        if brand is not None and _norm("brand", brand.value) != _norm("brand", variant.brand):
            continue
        if model is not None and model_key(str(model.value)) != model_key(variant.model):
            continue
        result.append(variant)
    return result


def best_candidates(
    offer: Attributes, variants: Iterable[VariantProfile], *, limit: int = 3
) -> list[Assessment]:
    scored = [assess(offer, v) for v in block_candidates(offer, variants)]
    return sorted(scored, key=lambda a: a.confidence_bp, reverse=True)[:limit]


def profile_from_catalog(
    variant_id: uuid.UUID,
    *,
    brand: str,
    model: str,
    mpn: str | None,
    gtin: str | None,
    attributes: Mapping[str, object],
) -> VariantProfile:
    def text(key: str) -> str | None:
        value = attributes.get(key)
        return str(value) if value not in (None, "") else None

    months = attributes.get("warranty_months")
    return VariantProfile(
        id=variant_id,
        brand=brand,
        model=model,
        mpn=mpn,
        gtin=gtin,
        capacity=text("capacity"),
        generation=text("generation"),
        frequency=text("frequency"),
        colour_edition=text("colour_edition"),
        warranty_provider=text("warranty_provider"),
        warranty_months=int(str(months)) if months not in (None, "") else None,
    )
