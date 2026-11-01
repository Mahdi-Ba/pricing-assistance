"""Generic page connector: loads a product page and extracts offers by rule.

The page loader is chosen by the source's retrieval method: plain HTTP for ``html``, a
headless browser only for ``rendered_page``.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pricing_assistant.core.text import normalize_key
from pricing_assistant.sources.connector import (
    Evidence,
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    ObservationDraft,
    OfferTarget,
)
from pricing_assistant.sources.extraction import ExtractionError, extract_page, parse_rule
from pricing_assistant.sources.models import RetrievalMethod


@dataclass(frozen=True, slots=True)
class LoadedPage:
    url: str
    html: bytes
    status: int
    latency_ms: int
    screenshot_png: bytes | None = None


PageLoader = Callable[[OfferTarget, FetchContext], Awaitable[LoadedPage | FetchFailure]]


def _decode(html: bytes) -> str:
    return html.decode("utf-8", errors="replace")


class PageConnector:
    def __init__(self, key: str, method: RetrievalMethod, loader: PageLoader) -> None:
        self.key = key
        self.method = method
        self._load = loader

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult:
        loaded = await self._load(target, ctx)
        if isinstance(loaded, FetchFailure):
            return loaded
        rule = None
        if ctx.extraction_rule is not None:
            try:
                rule = parse_rule(ctx.extraction_rule.config)
            except ValueError as exc:
                return FetchFailure(
                    FetchErrorClass.CONFIGURATION, str(exc), latency_ms=loaded.latency_ms
                )
        try:
            page = extract_page(
                _decode(loaded.html), base_url=loaded.url, unit=target.currency_unit, rule=rule
            )
        except ExtractionError as exc:
            return FetchFailure(
                FetchErrorClass.PARSE_FAILURE,
                str(exc),
                http_status=loaded.status,
                latency_ms=loaded.latency_ms,
            )
        offers = page.offers
        own_seller = ctx.connector_config.get("own_seller_name")
        if target.is_own_channel and isinstance(own_seller, str) and own_seller:
            # On a comparison channel's page, our listing is only our own seller row.
            offers = [o for o in offers if normalize_key(o.seller) == normalize_key(own_seller)]
            if not offers:
                return FetchFailure(
                    FetchErrorClass.UNEXPECTED_STRUCTURE,
                    "our own listing was not found on the channel page",
                    http_status=loaded.status,
                    latency_ms=loaded.latency_ms,
                )
        return ObservationDraft(
            target=target,
            observed_at=datetime.now(UTC),
            method=self.method,
            offers=offers,
            evidence=Evidence(
                html=loaded.html,
                extracted={
                    "method": page.method.value,
                    "offers": [
                        {
                            "seller": o.seller,
                            "price_rial": o.price_rial,
                            "stock": o.stock.value,
                            "title": o.title,
                        }
                        for o in page.offers
                    ],
                    **page.structured,
                },
                screenshot_png=loaded.screenshot_png,
            ),
            extraction_rule_version_id=(
                ctx.extraction_rule.version_id
                if ctx.extraction_rule is not None and page.method.value == "selectors"
                else None
            ),
            http_status=loaded.status,
            latency_ms=loaded.latency_ms,
        )
