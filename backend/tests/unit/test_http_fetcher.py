import uuid
from datetime import UTC, datetime

import httpx
import pytest

from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.connector import (
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    ObservationDraft,
    OfferTarget,
    StockState,
)
from pricing_assistant.sources.connectors.page import PageLoader
from pricing_assistant.sources.connectors.registry import ConnectorRegistry
from pricing_assistant.sources.http_fetcher import FetchedPage, HttpFetcher, parse_retry_after
from pricing_assistant.sources.models import RetrievalMethod
from tests.support.fixtures import fixture_text

UA = "PricingAssistanceBot/0.1 (+https://example.test/bot)"


def fetcher_for(handler: httpx.MockTransport) -> HttpFetcher:
    return HttpFetcher(user_agent=UA, transport=handler)


async def test_blocked_429_reports_retry_after_and_is_not_retried() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "600"})

    result = await fetcher_for(httpx.MockTransport(handler)).get(
        "https://www.lioncomputer.com/p/1", base_domain="lioncomputer.com"
    )
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.BLOCKED
    assert result.retry_after_seconds == 600
    assert result.retryable is False
    assert len(calls) == 1
    assert calls[0].headers["User-Agent"] == UA


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (403, b"", FetchErrorClass.BLOCKED),
        (200, b"<html><div class='g-recaptcha'></div></html>", FetchErrorClass.BLOCKED),
        (503, b"", FetchErrorClass.HTTP_ERROR),
        (404, b"", FetchErrorClass.NOT_FOUND),
        (400, b"", FetchErrorClass.CLIENT_ERROR),
    ],
)
async def test_status_classification(status: int, body: bytes, expected: FetchErrorClass) -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(status, content=body))
    result = await fetcher_for(transport).get("https://shop.test/p", base_domain="shop.test")
    assert isinstance(result, FetchFailure)
    assert result.error_class is expected
    assert result.retryable is (expected is FetchErrorClass.HTTP_ERROR)


async def test_off_domain_redirect_is_not_followed() -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://mirror.example.org/p"})

    result = await fetcher_for(httpx.MockTransport(handler)).get(
        "https://shop.test/p", base_domain="shop.test"
    )
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.OFF_DOMAIN
    assert hosts == ["shop.test"]


async def test_same_domain_redirect_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "https://www.shop.test/new"})
        return httpx.Response(200, content=b"<html>ok</html>")

    result = await fetcher_for(httpx.MockTransport(handler)).get(
        "https://shop.test/old", base_domain="shop.test"
    )
    assert isinstance(result, FetchedPage)
    assert result.url == "https://www.shop.test/new"


async def test_url_outside_cleared_domain_is_never_requested() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be called")

    result = await fetcher_for(httpx.MockTransport(handler)).get(
        "https://other.test/p", base_domain="shop.test"
    )
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.OFF_DOMAIN


def test_retry_after_http_date() -> None:
    now = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    assert parse_retry_after("Sun, 25 Oct 2026 12:05:00 GMT", now=now) == 300
    assert parse_retry_after("garbage") is None


async def test_html_source_never_starts_a_browser() -> None:
    def browser_factory() -> PageLoader:
        raise AssertionError("browser must not start for html sources")

    page = fixture_text("generic/jsonld_product.html").encode()
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, content=page))
    registry = ConnectorRegistry(
        http_fetcher=fetcher_for(transport), browser_loader_factory=browser_factory
    )
    connector = registry.connector_for("generic_html", RetrievalMethod.HTML)
    target = OfferTarget(
        tracked_offer_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        variant_id=uuid.uuid4(),
        url="https://www.lioncomputer.com/p/990",
        external_id=None,
        currency_unit=CurrencyUnit.TOMAN,
        base_domain="lioncomputer.com",
    )
    ctx = FetchContext(
        tenant_id=uuid.uuid4(), correlation_id="corr-html-0001", user_agent=UA, timeout_seconds=5
    )

    result = await connector.fetch(target, ctx)

    assert isinstance(result, ObservationDraft)
    assert result.method is RetrievalMethod.HTML
    assert result.offers[0].stock is StockState.IN_STOCK
    assert result.evidence.html == page
    assert result.evidence.screenshot_png is None


async def test_layout_change_becomes_parse_failure_without_any_fallback() -> None:
    page = fixture_text("generic/layout_changed.html").encode()
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, content=page))

    def browser_factory() -> PageLoader:
        raise AssertionError("no browser")

    registry = ConnectorRegistry(
        http_fetcher=fetcher_for(transport), browser_loader_factory=browser_factory
    )
    target = OfferTarget(
        tracked_offer_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        variant_id=uuid.uuid4(),
        url="https://shop.test/p",
        external_id=None,
        currency_unit=CurrencyUnit.TOMAN,
        base_domain="shop.test",
    )
    ctx = FetchContext(
        tenant_id=uuid.uuid4(), correlation_id="corr-html-0002", user_agent=UA, timeout_seconds=5
    )
    result = await registry.connector_for("generic_html", RetrievalMethod.HTML).fetch(target, ctx)
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.PARSE_FAILURE
