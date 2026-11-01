from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from pricing_assistant.app import create_app
from pricing_assistant.audit.api import list_events, record
from pricing_assistant.core.db import Database
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.iam.api import ExpertPrincipal, actor_of
from tests.support.tokens import issue_token, make_validator

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration


class NoteIn(BaseModel):
    text: str


@pytest.fixture
async def client(db: Database) -> AsyncIterator[httpx.AsyncClient]:
    router = APIRouter(route_class=IdempotentRoute)

    @router.post("/test/notes", status_code=201)
    async def create_note(body: NoteIn, principal: ExpertPrincipal) -> dict[str, str]:
        async with db.tenant_session(principal.tenant_id) as session:
            event_id = await record(
                session,
                tenant_id=principal.tenant_id,
                actor=actor_of(principal),
                action="test.note_created",
                target_type="note",
                reason=body.text,
            )
        return {"id": str(event_id), "text": body.text}

    @router.post("/test/explode")
    async def explode(principal: ExpertPrincipal) -> dict[str, str]:
        raise RuntimeError("boom")

    app = create_app(database=db, token_validator=make_validator(), extra_routers=[router])
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def headers(key: str | None, tenant: object = TENANT_A) -> dict[str, str]:
    token = issue_token(tenant_id=tenant, roles=["expert"])  # type: ignore[arg-type]
    result = {"Authorization": f"Bearer {token}"}
    if key is not None:
        result["Idempotency-Key"] = key
    return result


async def _notes(db: Database, tenant: object = TENANT_A) -> int:
    async with db.tenant_session(tenant) as session:  # type: ignore[arg-type]
        return len(await list_events(session, action="test.note_created"))


async def test_replayed_command_returns_original_response(
    client: httpx.AsyncClient, db: Database
) -> None:
    first = await client.post("/api/v1/test/notes", json={"text": "a"}, headers=headers("key-0001"))
    second = await client.post(
        "/api/v1/test/notes", json={"text": "a"}, headers=headers("key-0001")
    )

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    assert "Idempotency-Replayed" not in first.headers
    assert await _notes(db) == 1


async def test_same_key_with_different_payload_is_rejected(
    client: httpx.AsyncClient, db: Database
) -> None:
    await client.post("/api/v1/test/notes", json={"text": "a"}, headers=headers("key-0002"))
    reused = await client.post(
        "/api/v1/test/notes", json={"text": "b"}, headers=headers("key-0002")
    )

    assert reused.status_code == 422
    assert reused.json()["type"].endswith("idempotency_key_reused")
    assert await _notes(db) == 1


async def test_without_key_each_request_executes(client: httpx.AsyncClient, db: Database) -> None:
    for _ in range(2):
        assert (
            await client.post("/api/v1/test/notes", json={"text": "a"}, headers=headers(None))
        ).status_code == 201
    assert await _notes(db) == 2


async def test_keys_are_scoped_per_tenant(client: httpx.AsyncClient, db: Database) -> None:
    await client.post("/api/v1/test/notes", json={"text": "a"}, headers=headers("key-0003"))
    other = await client.post(
        "/api/v1/test/notes", json={"text": "a"}, headers=headers("key-0003", TENANT_B)
    )
    assert other.status_code == 201
    assert "Idempotency-Replayed" not in other.headers
    assert await _notes(db, TENANT_B) == 1


async def test_in_progress_duplicate_gets_409(client: httpx.AsyncClient, db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        await session.execute(
            text(
                "INSERT INTO idempotency_record (tenant_id, key, request_hash) "
                "VALUES (:t, 'key-0004', 'pending')"
            ),
            {"t": TENANT_A},
        )
    response = await client.post(
        "/api/v1/test/notes", json={"text": "a"}, headers=headers("key-0004")
    )
    assert response.status_code == 409
    assert response.json()["type"].endswith("idempotency_in_progress")


async def test_server_error_releases_key_for_retry(client: httpx.AsyncClient, db: Database) -> None:
    failed = await client.post("/api/v1/test/explode", headers=headers("key-0005"))
    assert failed.status_code == 500
    assert failed.json()["correlation_id"]
    async with db.tenant_session(TENANT_A) as session:
        remaining = (
            await session.execute(text("SELECT count(*) FROM idempotency_record"))
        ).scalar_one()
    assert remaining == 0


async def test_invalid_key_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/test/notes", json={"text": "a"}, headers=headers("x"))
    assert response.status_code == 422
    assert response.json()["type"].endswith("invalid_idempotency_key")
