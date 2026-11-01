"""Dramatiq broker setup and the outbox dispatcher that enqueues events for subscribers."""

from typing import Any

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware.asyncio import AsyncIO

from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.logging import get_logger
from pricing_assistant.core.outbox import Dispatcher, Subscriptions
from pricing_assistant.core.settings import Settings

log = get_logger(__name__)


def create_broker(settings: Settings) -> dramatiq.Broker:
    broker = RedisBroker(url=settings.redis_url.get_secret_value())  # type: ignore[no-untyped-call]
    broker.add_middleware(AsyncIO())
    dramatiq.set_broker(broker)
    return broker


def send(
    broker: dramatiq.Broker,
    *,
    actor_name: str,
    queue_name: str,
    payload: dict[str, Any],
    delay_ms: int | None = None,
) -> None:
    """Enqueue a message for an actor by name; the actor may live in another process."""
    broker.declare_queue(queue_name)
    message: dramatiq.Message[Any] = dramatiq.Message(
        queue_name=queue_name, actor_name=actor_name, args=(payload,), kwargs={}, options={}
    )
    broker.enqueue(message, delay=delay_ms)


def broker_dispatcher(broker: dramatiq.Broker, subscriptions: Subscriptions) -> Dispatcher:
    def dispatch(envelope: EventEnvelope) -> None:
        actors = subscriptions.actors_for(envelope.type)
        if not actors:
            log.debug("outbox.no_subscribers", event_type=envelope.type)
        payload = envelope.model_dump(mode="json")
        for actor_name in actors:
            send(
                broker,
                actor_name=actor_name,
                queue_name=subscriptions.queue_of(actor_name),
                payload=payload,
            )

    return dispatch
