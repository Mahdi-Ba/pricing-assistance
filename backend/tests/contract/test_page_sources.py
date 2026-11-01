"""Contract tests for the initial page sources against SYNTHETIC fixtures (tasks 6.4–6.6, 6.8).

Live use of every source is gated on its access clearance (Q-L1). Replace the fixtures with
recordings from the phase A qualification and adjust the rules until these tests pass again.
"""

from dataclasses import replace

import pytest

from pricing_assistant.sources.connector import (
    FetchErrorClass,
    FetchFailure,
    ObservationDraft,
    StockState,
)
from pricing_assistant.sources.models import RetrievalMethod
from tests.contract.harness import context_for, replay_registry, target_for
from tests.support.fixtures import fixture_json

ROUTES = {
    "/torob": "torob_page/product.html",
    "/digikala": "digikala_page/product.html",
    "/lion": "lion_computer/product.html",
    "/lion-oos": "lion_computer/out_of_stock.html",
    "/meghdad": "meghdad_it/product.html",
    "/own": "own_storefront/product.html",
    "/changed": "generic/layout_changed.html",
}
CONNECTOR = replay_registry(ROUTES, status={"/blocked": 403}).connector_for(
    "generic_html", RetrievalMethod.HTML
)


def rule(name: str) -> dict[str, object]:
    loaded: dict[str, object] = fixture_json(f"{name}/rule.json")
    return loaded


async def fetch(
    path: str,
    rule_name: str | None,
    *,
    is_own_store: bool = False,
    is_own_channel: bool = False,
    connector_config: dict[str, object] | None = None,
) -> ObservationDraft | FetchFailure:
    ctx = replace(
        context_for(rule(rule_name) if rule_name else None),
        connector_config=connector_config or {},
    )
    target = replace(
        target_for(f"https://shop.example{path}"),
        is_own_store=is_own_store,
        is_own_channel=is_own_channel,
    )
    result = await CONNECTOR.fetch(target, ctx)
    assert isinstance(result, ObservationDraft | FetchFailure)
    return result


async def test_torob_page_lists_every_shop() -> None:
    result = await fetch("/torob", "torob_page")
    assert isinstance(result, ObservationDraft)
    assert [(o.seller, o.price_rial, o.stock) for o in result.offers] == [
        ("لیون کامپیوتر", 86_000_000, StockState.IN_STOCK),
        ("فروشگاه ما", 88_900_000, StockState.IN_STOCK),
        ("مقداد آی‌تی", None, StockState.OUT_OF_STOCK),
    ]
    assert result.offers[0].conditions.warranty == "گارانتی ۳۶ ماهه آواژنگ"


async def test_own_torob_listing_keeps_only_our_row() -> None:
    result = await fetch(
        "/torob",
        "torob_page",
        is_own_channel=True,
        connector_config={"own_seller_name": "فروشگاه ما"},
    )
    assert isinstance(result, ObservationDraft)
    assert [(o.seller, o.price_rial) for o in result.offers] == [("فروشگاه ما", 88_900_000)]


async def test_own_listing_missing_is_unexpected_structure() -> None:
    result = await fetch(
        "/torob",
        "torob_page",
        is_own_channel=True,
        connector_config={"own_seller_name": "نام دیگر"},
    )
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.UNEXPECTED_STRUCTURE


async def test_digikala_page_reads_sellers_and_instalment() -> None:
    result = await fetch("/digikala", "digikala_page")
    assert isinstance(result, ObservationDraft)
    assert [(o.seller, o.price_rial, o.conditions.payment) for o in result.offers] == [
        ("رایان کامپیوتر", 184_500_000, None),
        ("تک‌نو", 189_000_000, "خرید اقساطی"),
    ]


async def test_lion_computer_compares_only_the_shops_own_offer() -> None:
    result = await fetch("/lion", "lion_computer")
    assert isinstance(result, ObservationDraft)
    assert [(o.seller, o.price_rial, o.stock) for o in result.offers] == [
        ("لیون کامپیوتر", 86_000_000, StockState.IN_STOCK)
    ]


async def test_lion_computer_out_of_stock() -> None:
    result = await fetch("/lion-oos", "lion_computer")
    assert isinstance(result, ObservationDraft)
    assert result.offers[0].stock is StockState.OUT_OF_STOCK
    assert result.offers[0].price_rial is None


async def test_meghdad_it_ready_to_ship_is_in_stock() -> None:
    result = await fetch("/meghdad", "meghdad_it")
    assert isinstance(result, ObservationDraft)
    assert [(o.seller, o.price_rial, o.stock) for o in result.offers] == [
        ("مقداد آی‌تی", 187_000_000, StockState.IN_STOCK)
    ]


async def test_own_storefront_price_from_structured_data() -> None:
    result = await fetch("/own", None, is_own_store=True)
    assert isinstance(result, ObservationDraft)
    assert result.offers[0].price_rial == 85_500_000
    assert result.target.is_own_store


@pytest.mark.parametrize("name", ["torob_page", "digikala_page", "lion_computer", "meghdad_it"])
async def test_layout_change_is_parse_failure(name: str) -> None:
    result = await fetch("/changed", name)
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.PARSE_FAILURE


async def test_blocked_page() -> None:
    result = await fetch("/blocked", "lion_computer")
    assert isinstance(result, FetchFailure)
    assert result.error_class is FetchErrorClass.BLOCKED
