"""Contract tests for the Torob Shop API connector against SYNTHETIC fixtures (see
fixtures/sources/README.md): replace them with recorded responses once access is confirmed."""

import uuid

import httpx
import pytest
from pydantic import ValidationError

from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.connector import (
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    ObservationDraft,
    OfferTarget,
    StockState,
)
from pricing_assistant.sources.connectors.torob_shop_api import (
    TorobShopApiConfig,
    TorobShopApiConnector,
)
from pricing_assistant.sources.http_fetcher import HttpFetcher
from tests.support.fixtures import FIXTURES

CONFIG: dict[str, object] = {
    "api_base_url": "https://api.torob.com",
    "product_path": "/v1/shop/products/{external_id}",
}
FILES = {
    "TRB-998877": "product.json",
    "TRB-112233": "out_of_stock.json",
    "TRB-0": "unexpected.json",
}


def _connector(seen: list[httpx.Request]) -> TorobShopApiConnector:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=(FIXTURES / "torob_shop_api" / FILES[key]).read_bytes())

    return TorobShopApiConnector(
        HttpFetcher(user_agent="test", transport=httpx.MockTransport(handler))
    )


def _target(external_id: str) -> OfferTarget:
    return OfferTarget(
        tracked_offer_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        variant_id=uuid.uuid4(),
        url=f"https://torob.com/p/{external_id}",
        external_id=external_id,
        currency_unit=CurrencyUnit.TOMAN,
        base_domain="torob.com",
        is_own_channel=True,
    )


def _ctx(config: dict[str, object] = CONFIG, token: str | None = "secret-token") -> FetchContext:
    return FetchContext(
        tenant_id=uuid.uuid4(),
        correlation_id="corr-torob-0001",
        user_agent="test",
        timeout_seconds=5,
        connector_config=config,
        secrets={"api_token": token} if token else {},
    )


async def test_own_listing_is_read_with_get_only() -> None:
    seen: list[httpx.Request] = []
    result = await _connector(seen).fetch(_target("TRB-998877"), _ctx())
    assert isinstance(result, ObservationDraft)
    [offer] = result.offers
    assert (offer.price_rial, offer.stock, offer.seller) == (
        88_900_000,
        StockState.IN_STOCK,
        "فروشگاه ما",
    )
    assert [r.method for r in seen] == ["GET"]
    assert seen[0].headers["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in repr(result)


async def test_explicit_unavailability() -> None:
    result = await _connector([]).fetch(_target("TRB-112233"), _ctx())
    assert isinstance(result, ObservationDraft)
    assert result.offers[0].stock is StockState.OUT_OF_STOCK
    assert result.offers[0].price_rial is None


async def test_changed_format_is_unexpected_structure() -> None:
    result = await _connector([]).fetch(_target("TRB-0"), _ctx())
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.UNEXPECTED_STRUCTURE


async def test_missing_token_sends_nothing() -> None:
    seen: list[httpx.Request] = []
    result = await _connector(seen).fetch(_target("TRB-998877"), _ctx(token=None))
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.CONFIGURATION
    assert seen == []


@pytest.mark.parametrize("scopes", [["write"], ["read", "write"], ["price:update"]])
def test_config_schema_has_no_write_scope(scopes: list[str]) -> None:
    with pytest.raises(ValidationError):
        TorobShopApiConfig.model_validate({**CONFIG, "scopes": scopes})


def test_api_base_url_must_be_https() -> None:
    with pytest.raises(ValidationError):
        TorobShopApiConfig.model_validate({**CONFIG, "api_base_url": "http://api.torob.com"})
