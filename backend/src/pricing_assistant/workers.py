"""Worker composition root: configures the Dramatiq broker and registers module actors.

Run with ``dramatiq pricing_assistant.workers --queues process`` (or ``collect``/``browser``).
"""

from collections.abc import Awaitable, Callable
from typing import Any

import dramatiq

from pricing_assistant.core.broker import create_broker
from pricing_assistant.core.consumer import idempotent_consumer
from pricing_assistant.core.correlation import set_correlation_id
from pricing_assistant.core.events import EventEnvelope
from pricing_assistant.core.logging import configure_logging
from pricing_assistant.core.metrics import serve_metrics
from pricing_assistant.core.registry import ConsumerSpec, RawHandler
from pricing_assistant.core.settings import get_settings
from pricing_assistant.core.tracing import configure_tracing
from pricing_assistant.wiring import consumer_specs, runtime

settings = get_settings()
configure_logging(level=settings.log_level, json=settings.log_json, service="worker")
configure_tracing(service=settings.service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint)
broker = create_broker(settings)
# imported once per Dramatiq worker process; run one process per pod so the port is free
serve_metrics(settings.metrics_port)


def _raw_actor(handler: RawHandler) -> Callable[[dict[str, Any]], Awaitable[None]]:
    async def run(message: dict[str, Any]) -> None:
        envelope = EventEnvelope.model_validate(message)
        set_correlation_id(envelope.correlation_id)
        await handler(envelope)

    return run


def _actor_fn(spec: ConsumerSpec) -> Callable[[dict[str, Any]], Awaitable[Any]]:
    if spec.raw is not None:
        return _raw_actor(spec.raw)
    assert spec.handler is not None  # noqa: S101 - ConsumerSpec guarantees one of the two
    return idempotent_consumer(spec.name, runtime.database)(spec.handler)


actors = {
    spec.name: dramatiq.actor(
        actor_name=spec.name,
        queue_name=spec.queue,
        broker=broker,
        max_retries=spec.max_retries,
        time_limit=spec.time_limit_ms,
    )(_actor_fn(spec))
    for spec in consumer_specs()
}
