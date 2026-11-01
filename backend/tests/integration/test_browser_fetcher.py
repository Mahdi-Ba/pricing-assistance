"""Rendered-page fetching against a local dynamic test page.

Needs a Playwright-compatible browser. If Playwright's own Chromium cannot be downloaded, set
``PA_BROWSER_CHANNEL=chrome`` to use an installed Google Chrome.
"""

import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest

from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.core.settings import get_settings
from pricing_assistant.sources.browser_fetcher import BrowserFetcher
from pricing_assistant.sources.connector import (
    ExtractionRule,
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    ObservationDraft,
    OfferTarget,
    StockState,
)
from pricing_assistant.sources.connectors.page import PageConnector
from pricing_assistant.sources.models import RetrievalMethod

pytestmark = pytest.mark.integration

DYNAMIC_PAGE = """<!doctype html><html lang="fa"><head><meta charset="utf-8"></head><body>
<h1>کارت گرافیک RTX 4060</h1>
<img src="/images/product.png">
<script src="https://cdn.other-domain.test/tracker.js"></script>
<div id="offer"></div>
<script>
setTimeout(function () {
  document.getElementById('offer').innerHTML =
    '<div class="seller-row"><span class="seller">رایان</span>' +
    '<span class="stock">موجود</span><span class="price">۱۸٬۴۵۰٬۰۰۰ تومان</span></div>';
}, 300);
</script></body></html>"""

RULE = {
    "offer_container": ".seller-row",
    "price": {"selector": ".price"},
    "stock": {"selector": ".stock", "in_stock": ["موجود"], "out_of_stock": ["ناموجود"]},
    "seller": {"selector": ".seller"},
}


class _Handler(BaseHTTPRequestHandler):
    requested: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        type(self).requested.append(self.path)
        if self.path == "/blocked":
            self.send_response(429)
            self.send_header("Retry-After", "120")
            self.end_headers()
            return
        body = DYNAMIC_PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _target(url: str) -> OfferTarget:
    return OfferTarget(
        tracked_offer_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        variant_id=uuid.uuid4(),
        url=url,
        external_id=None,
        currency_unit=CurrencyUnit.TOMAN,
        base_domain="127.0.0.1",
    )


def _ctx() -> FetchContext:
    return FetchContext(
        tenant_id=uuid.uuid4(),
        correlation_id="corr-browser-0001",
        user_agent="PricingAssistance/test",
        timeout_seconds=10,
        extraction_rule=ExtractionRule(version_id=uuid.uuid4(), config=RULE),
        connector_config={"wait_for_selector": ".seller-row .price"},
    )


@pytest.fixture
async def fetcher() -> AsyncIterator[BrowserFetcher]:
    settings = get_settings()
    browser = BrowserFetcher(
        user_agent=settings.collector_user_agent,
        page_timeout_seconds=15,
        channel=settings.browser_channel,
        executable_path=settings.browser_executable_path,
    )
    yield browser
    await browser.aclose()


async def test_dynamic_page_is_rendered_and_extracted(server: str, fetcher: BrowserFetcher) -> None:
    _Handler.requested.clear()
    connector = PageConnector("generic_html", RetrievalMethod.RENDERED_PAGE, fetcher.load)

    result = await connector.fetch(_target(f"{server}/p/4060"), _ctx())

    assert isinstance(result, ObservationDraft), result
    [offer] = result.offers
    assert (offer.seller, offer.price_rial, offer.stock) == (
        "رایان",
        184_500_000,
        StockState.IN_STOCK,
    )
    assert result.evidence.screenshot_png is not None
    assert result.evidence.screenshot_png.startswith(b"\x89PNG")
    assert result.method is RetrievalMethod.RENDERED_PAGE
    assert "/images/product.png" not in _Handler.requested  # images are blocked
    assert _Handler.requested == ["/p/4060"]


async def test_blocked_page_is_reported(server: str, fetcher: BrowserFetcher) -> None:
    result = await fetcher.load(_target(f"{server}/blocked"), _ctx())
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.BLOCKED
    assert result.retry_after_seconds == 120


async def test_off_domain_url_is_not_opened(fetcher: BrowserFetcher) -> None:
    result = await fetcher.load(_target("https://example.org/p"), _ctx())
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.OFF_DOMAIN


async def test_hard_timeout(server: str) -> None:
    settings = get_settings()
    slow = BrowserFetcher(
        user_agent="t",
        page_timeout_seconds=0.5,
        channel=settings.browser_channel,
        executable_path=settings.browser_executable_path,
    )
    ctx = FetchContext(
        tenant_id=uuid.uuid4(),
        correlation_id="corr-browser-0002",
        user_agent="t",
        timeout_seconds=1,
        connector_config={"wait_for_selector": ".never-appears"},
    )
    try:
        result = await slow.load(_target(f"{server}/p/1"), ctx)
    finally:
        await slow.aclose()
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.TIMEOUT
