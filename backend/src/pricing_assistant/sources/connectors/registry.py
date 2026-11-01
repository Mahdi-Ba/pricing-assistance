"""Maps a source's ``connector_key`` and retrieval method to a connector instance."""

from collections.abc import Callable

from pricing_assistant.sources.connector import (
    FetchContext,
    FetchFailure,
    OfferTarget,
    SourceConnector,
)
from pricing_assistant.sources.connectors.page import LoadedPage, PageConnector, PageLoader
from pricing_assistant.sources.http_fetcher import HttpFetcher
from pricing_assistant.sources.models import RetrievalMethod

GENERIC_PAGE = "generic_html"


def http_loader(fetcher: HttpFetcher) -> PageLoader:
    async def load(target: OfferTarget, ctx: FetchContext) -> LoadedPage | FetchFailure:
        result = await fetcher.get(target.url, base_domain=target.base_domain)
        if isinstance(result, FetchFailure):
            return result
        return LoadedPage(
            url=result.url, html=result.body, status=result.status, latency_ms=result.latency_ms
        )

    return load


class ConnectorRegistry:
    """Builds connectors lazily; a browser is created only for ``rendered_page`` sources."""

    def __init__(
        self,
        *,
        http_fetcher: HttpFetcher,
        browser_loader_factory: Callable[[], PageLoader],
        api_connectors: dict[str, SourceConnector] | None = None,
    ) -> None:
        self._http = http_fetcher
        self._browser_factory = browser_loader_factory
        self._browser_loader: PageLoader | None = None
        self._api = api_connectors or {}

    def _browser(self) -> PageLoader:
        if self._browser_loader is None:
            self._browser_loader = self._browser_factory()
        return self._browser_loader

    def connector_for(self, connector_key: str, method: RetrievalMethod) -> SourceConnector:
        if method is RetrievalMethod.API:
            try:
                return self._api[connector_key]
            except KeyError as exc:
                raise LookupError(f"no API connector registered for {connector_key!r}") from exc
        if method is RetrievalMethod.RENDERED_PAGE:
            return PageConnector(connector_key, method, self._browser())
        return PageConnector(connector_key, method, http_loader(self._http))
