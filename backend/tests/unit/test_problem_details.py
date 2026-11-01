import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from pricing_assistant.core.errors import Conflict, NotFound, install_error_handlers
from pricing_assistant.core.http import CorrelationMiddleware


class Body(BaseModel):
    price: int


def build_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(CorrelationMiddleware)

    @app.get("/missing")
    async def missing() -> None:
        raise NotFound("Recommendation not found")

    @app.post("/decide")
    async def decide(body: Body) -> None:
        raise Conflict(
            "Recommendation was superseded",
            code="recommendation_superseded",
            extra={"current_recommendation_id": "rec-2"},
        )

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal detail")

    return app


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=build_app(), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_app_error_maps_to_problem_details() -> None:
    async with await _client() as client:
        response = await client.get("/missing", headers={"X-Correlation-ID": "corr-12345678"})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "urn:pricing-assistance:problem:not_found",
        "title": "Not found",
        "status": 404,
        "detail": "Recommendation not found",
        "correlation_id": "corr-12345678",
        "message_fa": "مورد درخواستی یافت نشد.",
    }


async def test_conflict_carries_extra_fields() -> None:
    async with await _client() as client:
        response = await client.post("/decide", json={"price": 1})
    body = response.json()
    assert response.status_code == 409
    assert body["type"].endswith("recommendation_superseded")
    assert body["current_recommendation_id"] == "rec-2"


async def test_validation_errors_list_locations() -> None:
    async with await _client() as client:
        response = await client.post("/decide", json={"price": "abc"})
    body = response.json()
    assert response.status_code == 422
    assert body["errors"][0]["loc"] == ["body", "price"]


async def test_unhandled_errors_hide_internals() -> None:
    async with await _client() as client:
        response = await client.get("/crash")
    assert response.status_code == 500
    assert "secret internal detail" not in response.text
    assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]
