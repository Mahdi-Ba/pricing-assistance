import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from pricing_assistant.core.errors import install_error_handlers
from pricing_assistant.iam.api import Principal, get_principal
from tests.support.tokens import issue_token, make_validator

TENANT = uuid.UUID("0192f0a0-0000-7000-8000-000000000001")


def build_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.state.token_validator = make_validator()

    @app.get("/me")
    async def me(principal: Annotated[Principal, Depends(get_principal)]) -> dict[str, object]:
        return {
            "tenant_id": str(principal.tenant_id),
            "roles": sorted(principal.roles),
            "username": principal.username,
        }

    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=build_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_valid_token_yields_principal(client: httpx.AsyncClient) -> None:
    token = issue_token(tenant_id=TENANT, roles=["expert", "offline_access"])
    response = await client.get("/me", headers=bearer(token))
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": str(TENANT),
        "roles": ["expert"],
        "username": "pilot-expert",
    }


@pytest.mark.parametrize(
    ("case", "headers"),
    [
        ("missing", {}),
        ("not bearer", {"Authorization": "Basic abc"}),
        ("malformed", {"Authorization": "Bearer not-a-jwt"}),
        ("expired", bearer(issue_token(tenant_id=TENANT, roles=["expert"], expires_in=-120))),
        (
            "wrong audience",
            bearer(issue_token(tenant_id=TENANT, roles=["expert"], audience="other")),
        ),
        (
            "wrong issuer",
            bearer(issue_token(tenant_id=TENANT, roles=["expert"], issuer="https://evil")),
        ),
        (
            "bad signature",
            bearer(issue_token(tenant_id=TENANT, roles=["expert"], signed_by_other_key=True)),
        ),
        (
            "no tenant",
            bearer(issue_token(tenant_id=TENANT, roles=["expert"], extra={"tenant_id": "x"})),
        ),
    ],
)
async def test_rejected_tokens_return_401_without_data(
    client: httpx.AsyncClient, case: str, headers: dict[str, str]
) -> None:
    response = await client.get("/me", headers=headers)
    assert response.status_code == 401, case
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"].startswith("Bearer")
    body = response.json()
    assert body["type"] == "urn:pricing-assistance:problem:authentication_required"
    assert body["message_fa"]
    assert body["correlation_id"]
    assert "tenant_id" not in body
