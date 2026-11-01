"""Composition of per-process resources, event consumers and scheduled jobs.

Shared by the worker (actors) and the scheduler (event routing, jobs). Resources are created
lazily, on the event loop that first uses them.
"""

from functools import cache

import dramatiq
from redis.asyncio import Redis

from pricing_assistant.collection.evidence import EvidenceStore
from pricing_assistant.collection.fetching import handle_fetch
from pricing_assistant.collection.runtime import CollectionRuntime
from pricing_assistant.core.broker import send
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.registry import ConsumerSpec
from pricing_assistant.core.runtime import LazyDatabase
from pricing_assistant.core.settings import Settings, get_settings
from pricing_assistant.decisions import consumers as decisions
from pricing_assistant.llm.api import LLMPort, build_llm
from pricing_assistant.matching import consumers as matching
from pricing_assistant.pricing import consumers as pricing
from pricing_assistant.sources.browser_fetcher import BrowserFetcher
from pricing_assistant.sources.connectors.page import PageLoader
from pricing_assistant.sources.connectors.registry import ConnectorRegistry
from pricing_assistant.sources.connectors.torob_shop_api import TorobShopApiConnector
from pricing_assistant.sources.http_fetcher import HttpFetcher
from pricing_assistant.sources.ratelimit import SourceRateLimiter
from pricing_assistant.sources.suggestions import UrlSuggestionDeps, url_suggestion_handler

FETCH_ACTOR = "collection.fetch"
BROWSER_FETCH_ACTOR = "collection.fetch_browser"
RECOMPUTE_ACTOR = "pricing.recompute"
URL_SUGGESTION_ACTOR = "sources.suggest_offer_urls"
_ACTOR_FOR_EVENT = {
    "fetch.requested": FETCH_ACTOR,
    "fetch.requested.browser": BROWSER_FETCH_ACTOR,
    pricing.RECOMPUTE_TYPE: RECOMPUTE_ACTOR,
    "source.offer_urls.requested": URL_SUGGESTION_ACTOR,
}


class Runtime:
    """Lazily created resources of one worker or scheduler process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = LazyDatabase(
            settings.database_app_url, pool_size=settings.database_pool_size
        )
        self._redis: Redis | None = None
        self._evidence: EvidenceStore | None = None
        self._connectors: ConnectorRegistry | None = None
        self._http: HttpFetcher | None = None
        self._collection: CollectionRuntime | None = None
        self.llm: LLMPort = build_llm(settings, redis=self.redis, database=self.database)

    def redis(self) -> Redis:
        if self._redis is None:
            self._redis = Redis.from_url(self.settings.redis_url.get_secret_value())
        return self._redis

    def evidence(self) -> EvidenceStore:
        if self._evidence is None:
            self._evidence = EvidenceStore(self.settings)
        return self._evidence

    def http(self) -> HttpFetcher:
        if self._http is None:
            self._http = HttpFetcher(
                user_agent=self.settings.collector_user_agent,
                timeout_seconds=self.settings.collector_timeout_seconds,
            )
        return self._http

    def url_suggestions(self) -> UrlSuggestionDeps:
        return UrlSuggestionDeps(
            database=self.database,
            limiter=lambda: SourceRateLimiter(self.redis()),
            http=self.http,
            llm=self.llm,
            requeue=requeue,
        )

    def connectors(self) -> ConnectorRegistry:
        if self._connectors is None:
            settings = self.settings

            def browser() -> PageLoader:
                fetcher = BrowserFetcher(
                    user_agent=settings.collector_user_agent,
                    page_timeout_seconds=settings.browser_page_timeout_seconds,
                    channel=settings.browser_channel,
                    executable_path=settings.browser_executable_path,
                )
                return fetcher.load

            http = self.http()
            self._connectors = ConnectorRegistry(
                http_fetcher=http,
                browser_loader_factory=browser,
                api_connectors={TorobShopApiConnector.key: TorobShopApiConnector(http)},
            )
        return self._connectors

    def recompute_scheduler(self) -> "pricing.RecomputeScheduler":
        return pricing.RecomputeScheduler(self.redis, requeue)

    def collection(self) -> CollectionRuntime:
        if self._collection is None:
            self._collection = CollectionRuntime(
                settings=self.settings,
                database=self.database,
                redis=self.redis,
                evidence=self.evidence,
                connectors=self.connectors,
                requeue=requeue,
            )
        return self._collection


def requeue(envelope: EventEnvelope, delay_ms: int) -> None:
    """Send an envelope to its actor after a delay (retries, quota deferrals, debounce).

    Works from any process: the message is addressed by actor and queue name.
    """
    actor_name = _ACTOR_FOR_EVENT[envelope.type]
    send(
        dramatiq.get_broker(),
        actor_name=actor_name,
        queue_name=_queues()[actor_name],
        payload=envelope.model_dump(mode="json"),
        delay_ms=delay_ms,
    )


@cache
def _queues() -> dict[str, str]:
    return {spec.name: spec.queue for spec in consumer_specs()}


runtime = Runtime(get_settings())


async def _fetch(envelope: EventEnvelope) -> None:
    await handle_fetch(runtime.collection(), envelope)


def consumer_specs() -> list[ConsumerSpec]:
    """Every event consumer in the system."""
    return [
        ConsumerSpec(
            name=FETCH_ACTOR,
            event_types=("fetch.requested",),
            raw=_fetch,
            queue="collect",
            max_retries=0,  # retries are scheduled explicitly with backoff (collection.fetching)
            time_limit_ms=60_000,
        ),
        ConsumerSpec(
            name=BROWSER_FETCH_ACTOR,
            event_types=("fetch.requested.browser",),
            raw=_fetch,
            queue="browser",
            max_retries=0,
            time_limit_ms=90_000,
        ),
        ConsumerSpec(
            name=URL_SUGGESTION_ACTOR,
            event_types=("source.offer_urls.requested",),
            raw=url_suggestion_handler(runtime.url_suggestions()),
            queue="collect",  # outbound fetch: collector processes only
            max_retries=0,  # quota deferrals are re-queued explicitly
            time_limit_ms=120_000,
        ),
        ConsumerSpec(
            name="matching.normalize",
            event_types=("observation.recorded",),
            handler=matching.observation_handler(runtime.llm),
        ),
        ConsumerSpec(
            name="matching.match",
            event_types=("offer.attributes.updated",),
            handler=matching.attributes_handler(runtime.llm),
        ),
        ConsumerSpec(
            name="decisions.verify",
            event_types=("observation.recorded",),
            handler=decisions.on_observation_recorded,
        ),
        ConsumerSpec(
            name="pricing.triggers",
            event_types=pricing.TRIGGER_EVENTS,
            handler=pricing.trigger_handler(runtime.recompute_scheduler()),
        ),
        ConsumerSpec(
            name="pricing.rephrase",
            event_types=("recommendation.created",),
            handler=pricing.rephrase_handler(runtime.llm),
        ),
        ConsumerSpec(
            name=RECOMPUTE_ACTOR,
            event_types=(),  # sent directly (debounced), not via the outbox
            raw=pricing.recompute_handler(runtime.database),
        ),
    ]
