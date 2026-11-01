"""HTTP composition root: builds the FastAPI application and mounts module routers."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text

from pricing_assistant.catalog import http as catalog_http
from pricing_assistant.collection import http as collection_http
from pricing_assistant.collection.evidence import EvidenceStore
from pricing_assistant.core.db import Database, create_engine
from pricing_assistant.core.errors import install_error_handlers
from pricing_assistant.core.http import CorrelationMiddleware
from pricing_assistant.core.logging import configure_logging
from pricing_assistant.core.settings import Settings, get_settings
from pricing_assistant.core.tracing import configure_tracing, instrument_app
from pricing_assistant.decisions import http as decisions_http
from pricing_assistant.iam import settings_http
from pricing_assistant.iam.api import JwksCache, TokenValidator, get_principal, http_jwks_fetcher
from pricing_assistant.llm.api import LLMPort, build_llm
from pricing_assistant.matching import http as matching_http
from pricing_assistant.pricing import http as pricing_http
from pricing_assistant.reporting import http as reporting_http
from pricing_assistant.sources import http as sources_http
from pricing_assistant.workspace import http as workspace_http

API_PREFIX = "/api/v1"


def build_api_router() -> APIRouter:
    """All versioned API routes. Module routers are included here."""
    router = APIRouter(prefix=API_PREFIX)
    router.include_router(catalog_http.router)
    router.include_router(settings_http.router)
    router.include_router(collection_http.router)
    router.include_router(sources_http.router)
    router.include_router(pricing_http.router)
    router.include_router(decisions_http.router)
    router.include_router(matching_http.router)
    router.include_router(workspace_http.router)
    router.include_router(reporting_http.router)
    return router


async def _resolve_tenant(request: Request) -> uuid.UUID:
    return (await get_principal(request)).tenant_id


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    token_validator: TokenValidator | None = None,
    evidence_store: EvidenceStore | None = None,
    redis_client: Redis | None = None,
    llm: LLMPort | None = None,
    extra_routers: list[APIRouter] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json=settings.log_json, service="api")
    configure_tracing(
        service=settings.service_name, otlp_endpoint=settings.otel_exporter_otlp_endpoint
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = database is None
        if owned:
            app.state.db = Database(
                create_engine(settings.database_app_url, pool_size=settings.database_pool_size)
            )
        if token_validator is None:
            app.state.token_validator = TokenValidator(
                issuer=settings.oidc_issuer,
                audience=settings.oidc_audience,
                jwks=JwksCache(
                    http_jwks_fetcher(settings.jwks_url),
                    ttl_seconds=settings.oidc_jwks_cache_seconds,
                ),
                leeway_seconds=settings.oidc_leeway_seconds,
            )
        try:
            yield
        finally:
            if owned:
                await app.state.db.dispose()
            if redis_client is None:
                await app.state.redis.aclose()

    app = FastAPI(
        title="Tunoo Pricing Assistant",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.resolve_tenant = _resolve_tenant
    app.state.evidence_store = evidence_store or EvidenceStore(settings)
    app.state.redis = redis_client or Redis.from_url(settings.redis_url.get_secret_value())
    app.state.llm = llm or build_llm(
        settings, redis=lambda: app.state.redis, database=lambda: app.state.db
    )
    if database is not None:  # injected dependencies are available without running lifespan
        app.state.db = database
    if token_validator is not None:
        app.state.token_validator = token_validator
    install_error_handlers(app)
    app.add_middleware(CorrelationMiddleware)
    instrument_app(app)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        db: Database = app.state.db
        async with db.system_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    router = build_api_router()
    for extra in extra_routers or []:
        router.include_router(extra)
    app.include_router(router)
    return app
