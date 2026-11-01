"""Reference contract test for the generic page connector (see docs/connectors.md §5)."""

from pricing_assistant.sources.connector import (
    FetchErrorClass,
    FetchFailure,
    ObservationDraft,
    StockState,
)
from pricing_assistant.sources.models import RetrievalMethod
from tests.contract.harness import context_for, replay_registry, target_for
from tests.support.fixtures import fixture_json

RULE = fixture_json("generic/marketplace_rule.json")
REGISTRY = replay_registry(
    {
        "/p/990": "generic/jsonld_product.html",
        "/p/4060": "generic/microdata_product.html",
        "/p/sellers": "generic/marketplace_sellers.html",
        "/p/changed": "generic/layout_changed.html",
    },
    status={"/p/blocked": 429},
)
CONNECTOR = REGISTRY.connector_for("generic_html", RetrievalMethod.HTML)


async def test_page_with_price() -> None:
    result = await CONNECTOR.fetch(target_for("https://shop.example/p/990"), context_for(RULE))
    assert isinstance(result, ObservationDraft)
    assert result.offers[0].price_rial == 86_000_000
    assert result.evidence.html is not None
    assert result.evidence.extracted is not None
    assert result.extraction_rule_version_id is None  # structured data, rule not needed


async def test_marketplace_rows_use_the_active_rule() -> None:
    ctx = context_for(RULE)
    result = await CONNECTOR.fetch(target_for("https://shop.example/p/sellers"), ctx)
    assert isinstance(result, ObservationDraft)
    assert len(result.offers) == 4
    assert ctx.extraction_rule is not None
    assert result.extraction_rule_version_id == ctx.extraction_rule.version_id


async def test_explicit_out_of_stock() -> None:
    result = await CONNECTOR.fetch(target_for("https://shop.example/p/4060"), context_for(RULE))
    assert isinstance(result, ObservationDraft)
    assert result.offers[0].stock is StockState.OUT_OF_STOCK


async def test_changed_layout_is_parse_failure() -> None:
    result = await CONNECTOR.fetch(target_for("https://shop.example/p/changed"), context_for(RULE))
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.PARSE_FAILURE


async def test_blocked_is_not_retryable() -> None:
    result = await CONNECTOR.fetch(target_for("https://shop.example/p/blocked"), context_for(RULE))
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.BLOCKED
    assert result.retry_after_seconds == 300
    assert not result.retryable
