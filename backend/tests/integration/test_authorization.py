from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from pricing_assistant.audit.api import list_events
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import install_error_handlers
from pricing_assistant.iam.api import AdminPrincipal, ExpertPrincipal
from tests.support.tokens import issue_token, make_validator

from .conftest import TENANT_A

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    install_error_handlers(app)
    app.state.db = db
    app.state.token_validator = make_validator()

    @app.put("/api/v1/rules/default")
    async def update_rule(principal: AdminPrincipal) -> dict[str, str]:
        return {"updated_by": principal.username}

    @app.get("/api/v1/queue")
    async def queue(principal: ExpertPrincipal) -> dict[str, str]:
        return {"user": principal.username}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def auth(*roles: str) -> dict[str, str]:
    token = issue_token(tenant_id=TENANT_A, roles=list(roles), subject="sub-x", username="u-x")
    return {"Authorization": f"Bearer {token}"}


async def test_expert_calling_admin_endpoint_gets_403_and_is_audited(
    client: httpx.AsyncClient, db: Database
) -> None:
    response = await client.put("/api/v1/rules/default", headers=auth("expert"))

    assert response.status_code == 403
    assert response.json()["type"] == "urn:tunoo:pricing:problem:permission_denied"
    async with db.tenant_session(TENANT_A) as session:
        events = await list_events(session, action="authorization.denied")
    assert len(events) == 1
    assert events[0].outcome == "denied"
    assert events[0].actor_subject == "sub-x"
    assert events[0].target_id == "PUT /api/v1/rules/default"
    assert events[0].after == {"required_roles": ["admin"], "roles": ["expert"]}


async def test_admin_is_allowed_and_not_audited_as_denied(
    client: httpx.AsyncClient, db: Database
) -> None:
    response = await client.put("/api/v1/rules/default", headers=auth("admin"))
    assert response.status_code == 200
    async with db.tenant_session(TENANT_A) as session:
        assert await list_events(session, action="authorization.denied") == []


async def test_admin_may_use_expert_endpoints(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/queue", headers=auth("admin"))).status_code == 200
    assert (await client.get("/api/v1/queue", headers=auth("expert"))).status_code == 200
    assert (await client.get("/api/v1/queue", headers=auth())).status_code == 403
