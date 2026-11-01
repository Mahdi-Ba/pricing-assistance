"""Test doubles for connectors and page loaders."""

from datetime import UTC, datetime

from pricing_assistant.sources.connector import (
    Evidence,
    FetchContext,
    FetchResult,
    ObservationDraft,
    ObservedOffer,
    OfferTarget,
    StockState,
)
from pricing_assistant.sources.connectors.page import LoadedPage, PageLoader
from pricing_assistant.sources.connectors.registry import ConnectorRegistry
from pricing_assistant.sources.http_fetcher import HttpFetcher
from pricing_assistant.sources.models import RetrievalMethod


class RecordingConnector:
    """Returns queued results in order and records every target it was asked to fetch."""

    key = "fake"
    method = RetrievalMethod.HTML

    def __init__(self, *results: FetchResult) -> None:
        self.results = list(results)
        self.calls: list[OfferTarget] = []

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult:
        self.calls.append(target)
        if self.results:
            return self.results.pop(0)
        return draft(target, price_rial=86_000_000)


def draft(
    target: OfferTarget,
    *,
    price_rial: int | None = 86_000_000,
    stock: StockState = StockState.IN_STOCK,
    seller: str | None = "لیون کامپیوتر",
    html: bytes = b"<html>price</html>",
    title: str = "SSD 990 PRO",
) -> ObservationDraft:
    return ObservationDraft(
        target=target,
        observed_at=datetime.now(UTC),
        method=RetrievalMethod.HTML,
        offers=[ObservedOffer(price_rial=price_rial, stock=stock, seller=seller, title=title)],
        evidence=Evidence(html=html, extracted={"price_rial": price_rial}),
        http_status=200,
        latency_ms=12,
    )


class FixedRegistry(ConnectorRegistry):
    """A registry that always returns the given connector."""

    def __init__(self, connector: RecordingConnector) -> None:
        def no_browser() -> PageLoader:
            raise AssertionError("no browser in tests")

        super().__init__(
            http_fetcher=HttpFetcher(user_agent="test"), browser_loader_factory=no_browser
        )
        self.connector = connector

    def connector_for(self, connector_key: str, method: RetrievalMethod) -> RecordingConnector:
        return self.connector


__all__ = ["FixedRegistry", "LoadedPage", "RecordingConnector", "draft"]
