"""Read-only connector for our own shop's data through the Torob Shop API (task 6.3, Q-S2).

The store's Shop API access and the exact response format are not yet confirmed. The connector
is therefore configuration-driven: the endpoint path and the JSON field names come from the
source's connector config, so the confirmed contract can be applied without code changes. It
only ever sends ``GET`` requests, and its configuration schema accepts read scopes only.

Connector config::

    {
      "api_base_url": "https://api.torob.com",           # must be on the source's domain
      "product_path": "/v1/shop/products/{external_id}",
      "scopes": ["read"],
      "fields": {"price": "price", "available": "is_available", "title": "name",
                 "seller": "shop_name", "warranty": "warranty"}
    }

Secret: ``api_token`` (sent as ``Authorization: Bearer``).
"""

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pricing_assistant.core.money import MoneyParseError, parse_amount, to_rial
from pricing_assistant.sources.connector import (
    Evidence,
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    ObservationDraft,
    ObservedOffer,
    OfferConditions,
    OfferTarget,
    StockState,
)
from pricing_assistant.sources.http_fetcher import FetchedPage, HttpFetcher
from pricing_assistant.sources.models import RetrievalMethod


class FieldMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: str = "price"
    available: str = "is_available"
    title: str = "name"
    seller: str | None = "shop_name"
    warranty: str | None = "warranty"


def _read_only() -> list[Literal["read"]]:
    return ["read"]


class TorobShopApiConfig(BaseModel):
    """Only read scopes exist; anything else fails validation."""

    model_config = ConfigDict(extra="forbid")

    api_base_url: str = Field(pattern=r"^https://[a-z0-9.-]+(:\d+)?$")
    product_path: str = Field(
        default="/v1/shop/products/{external_id}", pattern=r"^/.*\{external_id\}.*$"
    )
    scopes: list[Literal["read"]] = Field(default_factory=_read_only, min_length=1)
    fields: FieldMap = Field(default_factory=FieldMap)
    estimated_cost_per_request_rial: int = 0


def _dig(data: Any, path: str | None) -> Any:
    if path is None:
        return None
    for part in path.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


class TorobShopApiConnector:
    key = "torob_shop_api"
    method = RetrievalMethod.API

    def __init__(self, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult:
        try:
            config = TorobShopApiConfig.model_validate(ctx.connector_config)
        except ValidationError as exc:
            return FetchFailure(
                FetchErrorClass.CONFIGURATION,
                f"invalid connector config: {exc.error_count()} errors",
            )
        token = ctx.secrets.get("api_token")
        if not token or not target.external_id:
            return FetchFailure(
                FetchErrorClass.CONFIGURATION, "api_token secret and external_id are required"
            )
        url = config.api_base_url + config.product_path.format(
            external_id=quote(target.external_id, safe="")
        )
        result = await self._fetcher.get(
            url,
            base_domain=target.base_domain,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if isinstance(result, FetchFailure):
            return result
        return self._parse(target, config, result)

    @staticmethod
    def _parse(target: OfferTarget, config: TorobShopApiConfig, page: FetchedPage) -> FetchResult:
        try:
            body = httpx.Response(200, content=page.body).json()
        except ValueError:
            return FetchFailure(
                FetchErrorClass.UNEXPECTED_STRUCTURE,
                "response is not JSON",
                http_status=page.status,
            )
        fields = config.fields
        available = _dig(body, fields.available)
        raw_price = _dig(body, fields.price)
        if available is None and raw_price is None:
            return FetchFailure(
                FetchErrorClass.UNEXPECTED_STRUCTURE,
                "price and availability fields missing",
                http_status=page.status,
            )
        stock = (
            StockState.UNKNOWN
            if available is None
            else (StockState.IN_STOCK if available else StockState.OUT_OF_STOCK)
        )
        price_rial: int | None = None
        if raw_price not in (None, ""):
            try:
                price_rial = to_rial(
                    parse_amount(raw_price if isinstance(raw_price, int) else str(raw_price)),
                    target.currency_unit,
                )
            except MoneyParseError:
                return FetchFailure(
                    FetchErrorClass.PARSE_FAILURE,
                    "price is not a whole amount",
                    http_status=page.status,
                )
        if price_rial is None and stock is not StockState.OUT_OF_STOCK:
            return FetchFailure(
                FetchErrorClass.PARSE_FAILURE,
                "no price for an available item",
                http_status=page.status,
            )
        offer = ObservedOffer(
            price_rial=price_rial,
            stock=stock,
            seller=_dig(body, fields.seller),
            title=_dig(body, fields.title),
            conditions=OfferConditions(warranty=_dig(body, fields.warranty)),
        )
        return ObservationDraft(
            target=target,
            observed_at=datetime.now(UTC),
            method=RetrievalMethod.API,
            offers=[offer],
            evidence=Evidence(
                html=page.body, extracted={"price_rial": price_rial, "stock": stock.value}
            ),
            http_status=page.status,
            latency_ms=page.latency_ms,
        )
