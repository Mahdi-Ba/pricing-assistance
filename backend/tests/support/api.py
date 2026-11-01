"""Helpers for API tests against an in-process app."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from pricing_assistant.app import create_app
from pricing_assistant.core.db import Database
from pricing_assistant.core.settings import Settings, get_settings
from pricing_assistant.llm.api import LLMPort
from tests.support.tokens import issue_token, make_validator


@asynccontextmanager
async def api_client(
    db: Database, settings: Settings | None = None, *, llm: LLMPort | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        settings or get_settings(), database=db, token_validator=make_validator(), llm=llm
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as client:
        yield client


def auth(tenant_id: uuid.UUID, *roles: str, username: str = "pilot-admin") -> dict[str, str]:
    token = issue_token(tenant_id=tenant_id, roles=list(roles), username=username, subject=username)
    return {"Authorization": f"Bearer {token}"}
