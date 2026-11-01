"""Plain HTTP fetching for ``api`` and ``html`` sources (design D5, task 4.6).

- Identifies itself with the configured User-Agent; never rotates identities or proxies
  (``trust_env=False`` ignores proxy environment variables).
- Fetches only URLs within the source's cleared domain; redirects are followed manually and
  must stay on that domain.
- HTTP 403/429 and bot-challenge pages are ``blocked``: not retried, ``Retry-After`` reported.
- Responses are size-capped and streamed.
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from pricing_assistant.sources.connector import FetchErrorClass, FetchFailure

MAX_REDIRECTS = 5
MAX_BODY_BYTES = 5 * 1024 * 1024
_BLOCKED_STATUS = frozenset({403, 429})
_NOT_FOUND_STATUS = frozenset({404, 410})
_CHALLENGE_MARKERS = (
    b"cf-challenge",
    b"challenge-platform",
    b"attention required",
    b"g-recaptcha",
    b"h-captcha",
    b"captcha-container",
    b"arvancloud-challenge",
    b"ddos-guard",
)


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    status: int
    body: bytes
    content_type: str
    latency_ms: int


def host_allowed(url: str, base_domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    domain = base_domain.lower().removeprefix("www.").rstrip(".")
    return urlsplit(url).scheme in {"http", "https"} and (
        host == domain or host.endswith("." + domain)
    )


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, int((when - (now or datetime.now(UTC))).total_seconds()))


def looks_like_challenge(body: bytes) -> bool:
    head = body[:20_000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


class HttpFetcher:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 15.0,
        max_concurrency_per_domain: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.5"},
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._max_per_domain = max_concurrency_per_domain
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self._max_per_domain)
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self, url: str, *, base_domain: str, headers: dict[str, str] | None = None
    ) -> FetchedPage | FetchFailure:
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        current = url
        async with self._semaphores[base_domain.lower()]:
            for _ in range(MAX_REDIRECTS + 1):
                if not host_allowed(current, base_domain):
                    return FetchFailure(
                        FetchErrorClass.OFF_DOMAIN,
                        f"URL outside the cleared domain {base_domain}",
                        latency_ms=elapsed(),
                    )
                try:
                    response, body = await self._request(current, headers)
                except httpx.TimeoutException:
                    return FetchFailure(
                        FetchErrorClass.TIMEOUT, "request timed out", latency_ms=elapsed()
                    )
                except httpx.TransportError as exc:
                    return FetchFailure(
                        FetchErrorClass.NETWORK, type(exc).__name__, latency_ms=elapsed()
                    )
                except _BodyTooLargeError:
                    return FetchFailure(
                        FetchErrorClass.UNEXPECTED_STRUCTURE,
                        "response body too large",
                        latency_ms=elapsed(),
                    )
                if response.is_redirect and "location" in response.headers:
                    current = urljoin(current, response.headers["location"])
                    continue
                return self._classify(current, response, body, elapsed())
        return FetchFailure(
            FetchErrorClass.CLIENT_ERROR, "too many redirects", latency_ms=elapsed()
        )

    async def _request(
        self, url: str, headers: dict[str, str] | None
    ) -> tuple[httpx.Response, bytes]:
        async with self._client.stream("GET", url, headers=headers) as response:
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise _BodyTooLargeError
                chunks.append(chunk)
            return response, b"".join(chunks)

    @staticmethod
    def _classify(
        url: str, response: httpx.Response, body: bytes, latency_ms: int
    ) -> FetchedPage | FetchFailure:
        status = response.status_code
        if status in _BLOCKED_STATUS or (status == 200 and looks_like_challenge(body)):  # noqa: PLR2004
            return FetchFailure(
                FetchErrorClass.BLOCKED,
                f"blocked by source (HTTP {status})",
                http_status=status,
                retry_after_seconds=parse_retry_after(response.headers.get("retry-after")),
                latency_ms=latency_ms,
            )
        if status in _NOT_FOUND_STATUS:
            return FetchFailure(
                FetchErrorClass.NOT_FOUND,
                f"HTTP {status}",
                http_status=status,
                latency_ms=latency_ms,
            )
        if status >= 500:  # noqa: PLR2004
            return FetchFailure(
                FetchErrorClass.HTTP_ERROR,
                f"HTTP {status}",
                http_status=status,
                retry_after_seconds=parse_retry_after(response.headers.get("retry-after")),
                latency_ms=latency_ms,
            )
        if status >= 400:  # noqa: PLR2004
            return FetchFailure(
                FetchErrorClass.CLIENT_ERROR,
                f"HTTP {status}",
                http_status=status,
                latency_ms=latency_ms,
            )
        return FetchedPage(
            url=url,
            status=status,
            body=body,
            content_type=response.headers.get("content-type", ""),
            latency_ms=latency_ms,
        )


class _BodyTooLargeError(Exception):
    pass
