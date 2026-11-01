"""Contract-test harness: replays recorded fixtures through the real connector stack."""

import uuid
from typing import Any

import httpx

from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.connector import ExtractionRule, FetchContext, OfferTarget
from pricing_assistant.sources.connectors.page import PageLoader
from pricing_assistant.sources.connectors.registry import ConnectorRegistry
from pricing_assistant.sources.http_fetcher import HttpFetcher
from tests.support.fixtures import FIXTURES

USER_AGENT = "TunooPricingAssistant/contract-test"


def replay_registry(
    routes: dict[str, str], *, status: dict[str, int] | None = None
) -> ConnectorRegistry:
    """Serve ``fixtures/sources/<file>`` for each path; paths not listed return 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in (status or {}):
            return httpx.Response((status or {})[path], headers={"Retry-After": "300"})
        if path not in routes:
            return httpx.Response(404)
        return httpx.Response(200, content=(FIXTURES / routes[path]).read_bytes())

    def no_browser() -> PageLoader:
        raise AssertionError("contract tests for html sources must not start a browser")

    return ConnectorRegistry(
        http_fetcher=HttpFetcher(user_agent=USER_AGENT, transport=httpx.MockTransport(handler)),
        browser_loader_factory=no_browser,
    )


def target_for(url: str, unit: CurrencyUnit = CurrencyUnit.TOMAN) -> OfferTarget:
    return OfferTarget(
        tracked_offer_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        variant_id=uuid.uuid4(),
        url=url,
        external_id=None,
        currency_unit=unit,
        base_domain=httpx.URL(url).host,
    )


def context_for(rule: dict[str, Any] | None = None) -> FetchContext:
    return FetchContext(
        tenant_id=uuid.uuid4(),
        correlation_id="corr-contract-0001",
        user_agent=USER_AGENT,
        timeout_seconds=5,
        extraction_rule=ExtractionRule(version_id=uuid.uuid4(), config=rule) if rule else None,
    )
