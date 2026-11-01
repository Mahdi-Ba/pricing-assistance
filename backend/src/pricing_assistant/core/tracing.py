"""OpenTelemetry tracing setup and log/trace correlation."""

from collections.abc import MutableMapping
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False


def configure_tracing(*, service: str, otlp_endpoint: str | None) -> None:
    """Install a tracer provider once per process. Without an endpoint spans are not exported,
    but trace IDs are still generated so logs can be correlated."""
    global _configured  # noqa: PLW0603 - process-wide, idempotent initialisation
    if _configured:
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service}))
    if otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    _configured = True


def instrument_app(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


def add_trace_context(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: attach the active trace and span IDs."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict
