"""HTTP middleware: correlation IDs, access logging and request metrics."""

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from pricing_assistant.core.correlation import HEADER, sanitize, set_correlation_id
from pricing_assistant.core.errors import AppError, problem_response
from pricing_assistant.core.logging import get_logger
from pricing_assistant.core.metrics import HTTP_REQUEST_SECONDS

log = get_logger("pricing_assistant.http")
_HEADER_BYTES = HEADER.lower().encode()


class CorrelationMiddleware:
    """Adopts a well-formed ``X-Correlation-ID`` from the caller or creates one, binds it for
    logs, events and audit records, and echoes it in the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        structlog.contextvars.clear_contextvars()
        incoming = next(
            (v.decode("latin-1") for k, v in scope["headers"] if k == _HEADER_BYTES), None
        )
        correlation_id = sanitize(incoming)
        set_correlation_id(correlation_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((_HEADER_BYTES, correlation_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Answer here rather than in Starlette's outer ServerErrorMiddleware so the
            # response still carries the correlation header; internals are never exposed.
            log.exception("request.unhandled_error", path=scope["path"])
            if response_started:
                raise
            response = problem_response(
                status=500,
                code=AppError.code,
                title=AppError.title,
                detail="An unexpected error occurred",
                message_fa=AppError.default_message_fa,
            )
            await response(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            HTTP_REQUEST_SECONDS.labels(scope["method"], route_path, str(status)).observe(elapsed)
            if route_path not in {"/healthz", "/readyz", "/metrics"}:
                log.info(
                    "http.request",
                    method=scope["method"],
                    path=scope["path"],
                    route=route_path,
                    status=status,
                    duration_ms=round(elapsed * 1000, 1),
                )
