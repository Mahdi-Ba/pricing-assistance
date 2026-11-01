"""Typed requests and responses of the LLM port.

Requests are an allow-list (task 8.2): every request model forbids extra fields and carries only
offer text, the public attributes of candidate variants and public page content of cleared
sources. Purchase cost, margins, profit rules, supplier data and personal data have no field
here, so they cannot be serialized into a request. Responses are validated strictly (task 8.4).
"""

import re
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

PUBLIC_ATTRIBUTE_KEYS = frozenset(
    {
        "capacity",
        "generation",
        "frequency",
        "colour_edition",
        "warranty_provider",
        "warranty_months",
    }
)
MAX_PAGE_CHARS = 40_000


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LLMTask(StrEnum):
    EXTRACT_ATTRIBUTES = "extract_attributes"
    PROPOSE_MATCH = "propose_match"
    REPHRASE_EXPLANATION = "rephrase_explanation"
    SUGGEST_EXTRACTION_RULE = "suggest_extraction_rule"
    SUGGEST_OFFER_URLS = "suggest_offer_urls"


# --- requests (allow-list) ----------------------------------------------------------------

Text = Annotated[str, StringConstraints(max_length=2_000)]


class CandidateVariant(Strict):
    """A variant as the model may see it: identity only, never cost or rules."""

    id: uuid.UUID
    brand: Text
    model: Text
    name: Text
    attributes: dict[str, str | int] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def _public_only(cls, value: dict[str, str | int]) -> dict[str, str | int]:
        unknown = set(value) - PUBLIC_ATTRIBUTE_KEYS
        if unknown:
            raise ValueError(
                f"non-public attributes may not be sent to the model: {sorted(unknown)}"
            )
        return value


class PageContent(Strict):
    """Public page content from a cleared source, trimmed to a bounded size."""

    url: Text
    content: Annotated[str, StringConstraints(max_length=MAX_PAGE_CHARS)]


class ExtractRequest(Strict):
    offer_text: Text


class MatchRequest(Strict):
    offer_text: Text
    candidates: Annotated[list[CandidateVariant], Field(min_length=1, max_length=10)]


class RephraseRequest(Strict):
    text: Text


class RuleRequest(Strict):
    samples: Annotated[list[PageContent], Field(min_length=1, max_length=3)]


class UrlRequest(Strict):
    variant: CandidateVariant
    search_page: PageContent


# --- responses (strictly validated) ----------------------------------------------------------


class ExtractedAttributes(Strict):
    brand: str | None
    model: str | None
    capacity: str | None
    generation: str | None
    frequency: str | None
    colour_edition: str | None
    warranty_provider: str | None
    warranty_months: Annotated[int, Field(ge=0, le=120)] | None
    condition: Literal["new", "used", "open_box", "unknown"]
    payment: Literal["cash", "instalment", "unknown"]

    @field_validator("capacity")
    @classmethod
    def _capacity_format(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"\d+(\.\d+)?(GB|TB)", value):
            raise ValueError("capacity must look like 512GB or 1TB")
        return value


class MatchProposal(Strict):
    variant_id: uuid.UUID | None
    confidence: Annotated[float, Field(ge=0, le=1)]
    rationale: Annotated[str, StringConstraints(max_length=1_000)]


class Rephrased(Strict):
    text: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]


class SelectorOut(Strict):
    selector: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    attribute: Annotated[str, StringConstraints(max_length=50)] | None  # e.g. "content"
    scope: Literal["offer", "page"]


class StockSelectorOut(SelectorOut):
    in_stock: list[str]
    out_of_stock: list[str]


class RuleSuggestion(Strict):
    offer_container: str | None
    price: SelectorOut
    stock: StockSelectorOut | None
    seller: SelectorOut | None
    title: SelectorOut | None
    warranty: SelectorOut | None
    rationale: Annotated[str, StringConstraints(max_length=1_000)]

    def to_rule_config(self) -> dict[str, Any]:
        """The selector config in the extraction-rule format (``sources`` validates it)."""
        return self.model_dump(exclude={"rationale"}, exclude_none=True)


class UrlCandidate(Strict):
    url: Annotated[str, StringConstraints(min_length=8, max_length=2_000)]
    confidence: Annotated[float, Field(ge=0, le=1)]
    rationale: Annotated[str, StringConstraints(max_length=500)]


class UrlSuggestions(Strict):
    candidates: Annotated[list[UrlCandidate], Field(max_length=5)]


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for structured outputs: every property required, no extra properties."""
    schema = model.model_json_schema()

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for key in ("default", "title"):
                node.pop(key, None)
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for item in node:
                tighten(item)

    tighten(schema)
    return schema
