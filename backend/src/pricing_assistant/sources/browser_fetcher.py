"""Headless-browser page loading for ``rendered_page`` sources only (design D5, task 4.7).

Each fetch uses a fresh browser context (no cookies or storage carried over), blocks images,
fonts and media, aborts every request outside the source's cleared domain, and is bounded by a
hard timeout. A PNG screenshot is kept as evidence. The browser worker has no database role
beyond writing observations and no access to secrets.
"""

import asyncio
import time
from dataclasses import dataclass, field

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    Response,
    Route,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from pricing_assistant.core.logging import get_logger
from pricing_assistant.sources.connector import (
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    OfferTarget,
)
from pricing_assistant.sources.connectors.page import LoadedPage
from pricing_assistant.sources.http_fetcher import (
    host_allowed,
    looks_like_challenge,
    parse_retry_after,
)

_BLOCKED_RESOURCES = frozenset({"image", "font", "media"})
_BLOCKED_STATUS = frozenset({403, 429})
log = get_logger(__name__)


@dataclass
class _Navigation:
    """Status of the main document, captured even when Chrome aborts navigation (e.g. 429)."""

    started: float = field(default_factory=time.perf_counter)
    status: int | None = None
    retry_after: str | None = None

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def remember(self, response: Response) -> None:
        if response.request.is_navigation_request() and self.status is None:
            self.status = response.status
            self.retry_after = response.headers.get("retry-after")

    def blocked(self) -> FetchFailure:
        return FetchFailure(
            FetchErrorClass.BLOCKED,
            f"blocked by source (HTTP {self.status} or challenge page)",
            http_status=self.status,
            retry_after_seconds=parse_retry_after(self.retry_after),
            latency_ms=self.elapsed_ms(),
        )

    def is_blocked(self) -> bool:
        return self.status in _BLOCKED_STATUS


class BrowserFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        page_timeout_seconds: float,
        channel: str | None = None,
        executable_path: str | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = page_timeout_seconds
        self._channel = channel
        self._executable_path = executable_path
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self) -> Browser:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    channel=self._channel,
                    executable_path=self._executable_path,
                    args=["--disable-dev-shm-usage", "--no-first-run"],
                )
            return self._browser

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def load(self, target: OfferTarget, ctx: FetchContext) -> LoadedPage | FetchFailure:
        if not host_allowed(target.url, target.base_domain):
            return FetchFailure(FetchErrorClass.OFF_DOMAIN, "URL outside the cleared domain")
        navigation = _Navigation()
        try:
            return await asyncio.wait_for(self._load(target, ctx, navigation), self._timeout)
        except TimeoutError:
            return FetchFailure(
                FetchErrorClass.TIMEOUT,
                "page render exceeded the hard timeout",
                latency_ms=navigation.elapsed_ms(),
            )

    async def _new_context(self, base_domain: str) -> BrowserContext:
        browser = await self._ensure_browser()
        context = await browser.new_context(
            user_agent=self._user_agent,
            locale="fa-IR",
            timezone_id="Asia/Tehran",
            service_workers="block",
            accept_downloads=False,
        )

        async def guard(route: Route) -> None:
            request = route.request
            if request.resource_type in _BLOCKED_RESOURCES or not host_allowed(
                request.url, base_domain
            ):
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", guard)
        return context

    async def _load(
        self, target: OfferTarget, ctx: FetchContext, navigation: _Navigation
    ) -> LoadedPage | FetchFailure:
        context = await self._new_context(target.base_domain)
        try:
            page = await context.new_page()
            page.on("response", navigation.remember)
            page.set_default_timeout(self._timeout * 1000)
            await page.goto(target.url, wait_until="domcontentloaded")
            if navigation.is_blocked():
                return navigation.blocked()
            wait_for = ctx.connector_config.get("wait_for_selector")
            if isinstance(wait_for, str) and wait_for:
                await page.wait_for_selector(wait_for, state="attached")
            else:
                await page.wait_for_load_state("networkidle")
            html = (await page.content()).encode("utf-8")
            if looks_like_challenge(html):
                return navigation.blocked()
            return LoadedPage(
                url=page.url,
                html=html,
                status=navigation.status or 0,
                latency_ms=navigation.elapsed_ms(),
                screenshot_png=await page.screenshot(type="png", full_page=False),
            )
        except PlaywrightTimeoutError:
            return FetchFailure(
                FetchErrorClass.TIMEOUT,
                "page element did not appear in time",
                latency_ms=navigation.elapsed_ms(),
            )
        except PlaywrightError as exc:
            if navigation.is_blocked():
                return navigation.blocked()
            log.warning("browser.fetch_failed", error=str(exc)[:200])
            return FetchFailure(
                FetchErrorClass.NETWORK,
                "browser navigation failed",
                latency_ms=navigation.elapsed_ms(),
            )
        finally:
            await context.close()
