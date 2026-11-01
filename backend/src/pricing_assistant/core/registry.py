"""Declarative wiring of event consumers, shared by the worker and scheduler processes.

Modules contribute :class:`ConsumerSpec` entries; the worker turns them into Dramatiq actors
and the scheduler's outbox relay uses the same list to route events to those actors.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from pricing_assistant.core.consumer import Handler
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.outbox import Subscriptions

RawHandler = Callable[[EventEnvelope], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ConsumerSpec:
    """An event consumer.

    ``handler`` consumers run exactly once per event inside one tenant transaction
    (``core.consumer.consume``). ``raw`` consumers manage their own transactions and
    deduplication, for work that must not hold a transaction open, such as network fetches.
    """

    name: str
    event_types: tuple[str, ...]
    handler: Handler | None = None
    raw: RawHandler | None = None
    queue: str = "process"
    max_retries: int = 5
    time_limit_ms: int = 120_000

    def __post_init__(self) -> None:
        if (self.handler is None) == (self.raw is None):
            raise ValueError(f"consumer {self.name} needs exactly one of handler or raw")


def subscriptions_for(specs: Iterable[ConsumerSpec]) -> Subscriptions:
    subscriptions = Subscriptions()
    for spec in specs:
        subscriptions.register(spec.name, spec.queue)
        for event_type in spec.event_types:
            subscriptions.subscribe(event_type, spec.name, spec.queue)
    return subscriptions
