"""Messages are addressed by actor and queue name, so the scheduler (which declares no actors)
can relay events to actors that only the worker processes declare."""

import uuid
from datetime import UTC, datetime

import dramatiq
from dramatiq.brokers.stub import StubBroker

from pricing_assistant.core.broker import broker_dispatcher
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.registry import subscriptions_for
from pricing_assistant.wiring import consumer_specs, requeue


def _envelope(event_type: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=uuid.uuid4(),
        type=event_type,
        version=1,
        tenant_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        correlation_id="c",
        payload={"variant_id": str(uuid.uuid4())},
    )


def _messages(broker: StubBroker, queue: str) -> list[dramatiq.Message[object]]:
    return [dramatiq.Message.decode(raw) for raw in broker.queues[queue].queue]


def test_relay_routes_to_actor_queues_without_declared_actors() -> None:
    broker = StubBroker()
    assert broker.actors == {}
    dispatch = broker_dispatcher(broker, subscriptions_for(consumer_specs()))
    dispatch(_envelope("observation.recorded"))
    names = sorted(m.actor_name for m in _messages(broker, "process"))
    assert names == ["decisions.verify", "matching.normalize", "pricing.triggers"]
    dispatch(_envelope("source.offer_urls.requested"))
    [message] = _messages(broker, "collect")
    assert message.actor_name == "sources.suggest_offer_urls"


def test_requeue_works_from_a_process_without_actors() -> None:
    broker = StubBroker()
    dramatiq.set_broker(broker)
    requeue(_envelope("pricing.recompute.requested"), 5_000)
    [message] = _messages(broker, "process.DQ")
    assert message.actor_name == "pricing.recompute"
    assert message.options["eta"] > 0
