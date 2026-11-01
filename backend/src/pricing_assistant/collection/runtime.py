"""Resources the collection workers need, created lazily on the worker's event loop."""

from collections.abc import Callable
from dataclasses import dataclass, field

from redis.asyncio import Redis

from pricing_assistant.collection.evidence import EvidenceStore
from pricing_assistant.core.crypto import SecretBox
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.settings import Settings
from pricing_assistant.sources.api import ConnectorRegistry, RecheckBudget, SourceRateLimiter

# Re-enqueue an envelope after ``delay_ms`` on the same actor (retries, quota deferrals).
Requeue = Callable[[EventEnvelope, int], None]


@dataclass
class CollectionRuntime:
    settings: Settings
    database: Callable[[], Database]
    redis: Callable[[], Redis]
    evidence: Callable[[], EvidenceStore]
    connectors: Callable[[], ConnectorRegistry]
    requeue: Requeue
    box: SecretBox = field(init=False)

    def __post_init__(self) -> None:
        self.box = SecretBox.from_setting(self.settings.secret_encryption_keys)

    def limiter(self) -> SourceRateLimiter:
        return SourceRateLimiter(self.redis())

    def recheck_budget(self) -> RecheckBudget:
        return RecheckBudget(self.redis())
