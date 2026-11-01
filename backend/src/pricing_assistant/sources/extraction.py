"""Rule-based price and stock extraction from HTML (design D5, task 4.4).

Structured data (JSON-LD or microdata ``Offer``) is tried first. If a page has none, the
source's active selector rule is applied. Nothing here interprets page text as instructions,
and no language model reads prices.

Selector rule configuration (stored per source in ``extraction_rule_version.config``)::

    {
      "offer_container": ".seller-row",          # optional: one block per seller offer
      "price": {"selector": ".price"},
      "stock": {"selector": ".stock", "in_stock": ["موجود"], "out_of_stock": ["ناموجود"]},
      "seller": {"selector": ".seller"},          # or "fixed_seller": "Lion Computer"
      "title": {"selector": "h1", "scope": "page"},
      "warranty": {"selector": ".warranty"},
      "condition": {"selector": ".condition"},
      "payment": {"selector": ".payment"}
    }
"""

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

import extruct
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from selectolax.lexbor import LexborHTMLParser, LexborNode

from pricing_assistant.core.money import (
    CurrencyUnit,
    MoneyParseError,
    normalize_digits,
    parse_amount,
    to_rial,
)
from pricing_assistant.sources.connector import ObservedOffer, OfferConditions, StockState

_NUMBER = re.compile(r"\d[\d,٬،\s]*")
_IN_STOCK = {"instock", "limitedavailability", "onlineonly", "instoreonly"}
_OUT_OF_STOCK = {"outofstock", "soldout", "discontinued"}


class ExtractionMethod(StrEnum):
    STRUCTURED_DATA = "structured_data"
    SELECTORS = "selectors"


class ExtractionError(Exception):
    """No price could be extracted; the fetch is recorded as a parse failure."""


class FieldSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: str = Field(min_length=1, max_length=300)
    attribute: str | None = None
    scope: Literal["offer", "page"] = "offer"


class StockSelector(FieldSelector):
    in_stock: list[str] = Field(default_factory=list)
    out_of_stock: list[str] = Field(default_factory=list)


class SelectorRule(BaseModel):
    """Validated selector configuration of one extraction rule version."""

    model_config = ConfigDict(extra="forbid")

    offer_container: str | None = Field(default=None, max_length=300)
    price: FieldSelector
    stock: StockSelector | None = None
    seller: FieldSelector | None = None
    fixed_seller: str | None = Field(default=None, max_length=200)
    title: FieldSelector | None = None
    warranty: FieldSelector | None = None
    condition: FieldSelector | None = None
    payment: FieldSelector | None = None


def parse_rule(config: dict[str, Any]) -> SelectorRule:
    try:
        return SelectorRule.model_validate(config)
    except ValidationError as exc:
        raise ValueError(f"invalid extraction rule: {exc.errors(include_url=False)}") from exc


@dataclass(frozen=True, slots=True)
class PageExtraction:
    method: ExtractionMethod
    offers: list[ObservedOffer]
    structured: dict[str, Any] = field(default_factory=dict)


def _price_rial(raw: object, unit: CurrencyUnit) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return to_rial(int(raw), unit) if raw > 0 and float(raw).is_integer() else None
    match = _NUMBER.search(normalize_digits(str(raw)))
    if not match:
        return None
    try:
        amount = parse_amount(match.group(0).strip(" ,"))
    except MoneyParseError:
        return None
    return to_rial(amount, unit) if amount > 0 else None


def _availability(value: object) -> StockState:
    text = str(value or "").rsplit("/", 1)[-1].strip().lower()
    if text in _OUT_OF_STOCK:
        return StockState.OUT_OF_STOCK
    if text in _IN_STOCK:
        return StockState.IN_STOCK
    return StockState.UNKNOWN


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _name_of(value: object) -> str | None:
    if isinstance(value, dict):
        name = _props(value).get("name")
        return str(name).strip() if name else None
    return str(value).strip() if value else None


def _types(item: dict[str, Any]) -> set[str]:
    raw = item.get("@type") or item.get("type") or []
    return {str(t).rsplit("/", 1)[-1] for t in _as_list(raw)}


def _props(item: dict[str, Any]) -> dict[str, Any]:
    """Microdata items keep values under 'properties'; JSON-LD items are flat."""
    properties = item.get("properties")
    return properties if isinstance(properties, dict) else item


def _walk_products(items: list[Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    stack = list(items)
    while stack:
        item = stack.pop(0)
        if not isinstance(item, dict):
            continue
        if "@graph" in item:
            stack.extend(_as_list(item["@graph"]))
        if "Product" in _types(item):
            found.append(item)
    return found


def extract_structured(html: str, base_url: str, unit: CurrencyUnit) -> PageExtraction | None:
    data = extruct.extract(
        html, base_url=base_url, syntaxes=["json-ld", "microdata"], uniform=False
    )
    products = _walk_products([*data.get("json-ld", []), *data.get("microdata", [])])
    offers: list[ObservedOffer] = []
    for product in products:
        props = _props(product)
        identifiers = {
            key: str(props[key])
            for key in ("sku", "mpn", "gtin", "gtin8", "gtin12", "gtin13", "gtin14")
            if props.get(key)
        }
        title = _name_of(props.get("name"))
        for raw_offer in _as_list(props.get("offers")):
            if not isinstance(raw_offer, dict):
                continue
            offer = _props(raw_offer)
            nested = _as_list(offer.get("offers")) if "AggregateOffer" in _types(raw_offer) else []
            for leaf in nested or [offer]:
                leaf_props = _props(leaf) if isinstance(leaf, dict) else {}
                price = _price_rial(leaf_props.get("price") or leaf_props.get("lowPrice"), unit)
                if price is None:
                    continue
                offers.append(
                    ObservedOffer(
                        price_rial=price,
                        stock=_availability(leaf_props.get("availability")),
                        seller=_name_of(leaf_props.get("seller")),
                        title=title,
                        conditions=OfferConditions(
                            condition=_availability_free(leaf_props.get("itemCondition")),
                            warranty=_name_of(leaf_props.get("warranty")),
                        ),
                        identifiers=identifiers,
                    )
                )
    if not offers:
        return None
    return PageExtraction(
        method=ExtractionMethod.STRUCTURED_DATA,
        offers=offers,
        structured={"products": json.loads(json.dumps(products, default=str))},
    )


def _availability_free(value: object) -> str | None:
    """schema.org itemCondition (e.g. NewCondition) as a short raw string."""
    if not value:
        return None
    return str(value).rsplit("/", 1)[-1]


def _text(node: LexborNode | None, attribute: str | None) -> str | None:
    if node is None:
        return None
    value = node.attributes.get(attribute) if attribute else node.text(separator=" ", strip=True)
    return value.strip() if value else None


def _select(page: LexborNode, block: LexborNode, spec: FieldSelector | None) -> str | None:
    if spec is None:
        return None
    root = page if spec.scope == "page" else block
    return _text(root.css_first(spec.selector), spec.attribute)


def _stock(page: LexborNode, block: LexborNode, spec: StockSelector | None) -> StockState:
    text = _select(page, block, spec)
    if spec is None or text is None:
        return StockState.UNKNOWN
    normalized = normalize_digits(text)
    # Out-of-stock phrases first: «ناموجود» contains «موجود».
    if any(p in normalized for p in spec.out_of_stock):
        return StockState.OUT_OF_STOCK
    if any(p in normalized for p in spec.in_stock):
        return StockState.IN_STOCK
    return StockState.UNKNOWN


def extract_with_rule(html: str, rule: SelectorRule, unit: CurrencyUnit) -> PageExtraction:
    tree = LexborHTMLParser(html)
    page = tree.root
    if page is None:
        raise ExtractionError("empty document")
    blocks = tree.css(rule.offer_container) if rule.offer_container else [page]
    offers: list[ObservedOffer] = []
    for block in blocks:
        price = _price_rial(_select(page, block, rule.price), unit)
        stock = _stock(page, block, rule.stock)
        if price is None and stock is not StockState.OUT_OF_STOCK:
            continue
        offers.append(
            ObservedOffer(
                price_rial=price,
                stock=stock,
                seller=rule.fixed_seller or _select(page, block, rule.seller),
                title=_select(page, block, rule.title),
                conditions=OfferConditions(
                    warranty=_select(page, block, rule.warranty),
                    condition=_select(page, block, rule.condition),
                    payment=_select(page, block, rule.payment),
                ),
            )
        )
    if not offers:
        raise ExtractionError("no offer with a price matched the extraction rule")
    return PageExtraction(method=ExtractionMethod.SELECTORS, offers=offers)


def extract_page(
    html: str, *, base_url: str, unit: CurrencyUnit, rule: SelectorRule | None
) -> PageExtraction:
    """Structured data first, then the active selector rule; raise if neither yields offers."""
    structured = extract_structured(html, base_url, unit)
    if structured is not None:
        return structured
    if rule is None:
        raise ExtractionError("page has no structured offer data and the source has no active rule")
    return extract_with_rule(html, rule, unit)
