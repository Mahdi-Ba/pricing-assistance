"""LLM suggestions for sources: extraction rules (8.9) and offer URLs (8.10)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from pricing_assistant.audit.api import list_events
from pricing_assistant.collection.scheduling import schedule_due
from pricing_assistant.core.db import Database
from pricing_assistant.core.events import EventEnvelope, OutboxEventRow
from pricing_assistant.llm.adapters import Completion
from pricing_assistant.llm.api import LLMService, LLMTask, NullLLMAdapter, RecordedAdapter
from pricing_assistant.sources import config, rules
from pricing_assistant.sources.http_fetcher import HttpFetcher
from pricing_assistant.sources.models import ExtractionRuleVersionRow, TrackedOfferRow
from pricing_assistant.sources.ratelimit import SourceRateLimiter
from pricing_assistant.sources.runtime import active_rule
from pricing_assistant.sources.suggestions import UrlSuggestionDeps, url_suggestion_handler
from tests.support.api import api_client, auth
from tests.support.fixtures import FIXTURES
from tests.support.seed import ADMIN, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration

ADMIN_AUTH = auth(TENANT_A, "admin")
EXPERT_AUTH = auth(TENANT_A, "expert", username="pilot-expert")
SITE = "https://www.lioncomputer.com"
RULE_ANSWER = {
    "offer_container": ".seller-row",
    "price": {"selector": ".price", "attribute": None, "scope": "offer"},
    "stock": {
        "selector": ".stock",
        "attribute": None,
        "scope": "offer",
        "in_stock": ["موجود"],
        "out_of_stock": ["ناموجود", "اتمام موجودی"],
    },
    "seller": {"selector": ".seller-name", "attribute": None, "scope": "offer"},
    "title": {"selector": "h1.product-title", "attribute": None, "scope": "page"},
    "warranty": {"selector": ".warranty", "attribute": None, "scope": "offer"},
    "rationale": "Each seller is a .seller-row block with its own price and stock.",
}


def recorded(responses: dict[LLMTask, Any]) -> tuple[LLMService, RecordedAdapter]:
    adapter = RecordedAdapter(responses)
    return LLMService(adapter, budget=None), adapter


async def _source_with_sample(db: Database) -> uuid.UUID:
    source = await seed_source(db, TENANT_A)
    async with db.tenant_session(TENANT_A) as session:
        await rules.add_sample(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=source,
            url=f"{SITE}/p/sellers",
            html=(FIXTURES / "generic/marketplace_sellers.html").read_bytes(),
        )
    return source


# --- 8.9 extraction rule suggestion --------------------------------------------------------


async def test_suggested_rule_is_stored_as_proposed_with_sample_results(db: Database) -> None:
    source = await _source_with_sample(db)
    llm, adapter = recorded(
        {LLMTask.SUGGEST_EXTRACTION_RULE: json.dumps(RULE_ANSWER, ensure_ascii=False)}
    )
    async with api_client(db, llm=llm) as client:
        response = await client.post(
            f"/sources/{source}/extraction-rules/suggest", headers=ADMIN_AUTH
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["state"], body["origin"]) == ("proposed", "llm")
    assert body["validation"]["passed"] is True
    assert body["validation"]["results"][0]["offers"] >= 2
    assert body["config"]["offer_container"] == ".seller-row"

    sent = adapter.calls[0].user
    assert sent.startswith('<untrusted_data source="sample:')
    assert "<script" not in sent  # compacted: no scripts or styles go to the model
    async with db.tenant_session(TENANT_A) as session:
        assert await active_rule(session, source) is None  # not used until an admin approves
        [audit] = await list_events(session, action="source.extraction_rule.suggested")
        assert audit.after is not None
        assert audit.after["rationale"].startswith("Each seller")

    async with api_client(db, llm=llm) as client:
        review = await client.post(
            f"/extraction-rules/{body['id']}/review",
            json={"decision": "approve", "reason": "checked on samples"},
            headers=ADMIN_AUTH,
        )
    assert review.json()["state"] == "active"


async def test_invalid_or_unavailable_suggestions_create_nothing(db: Database) -> None:
    source = await _source_with_sample(db)
    bad = {**RULE_ANSWER, "price": {"selector": "", "attribute": None, "scope": "offer"}}
    cases = [
        (LLMService(NullLLMAdapter(), budget=None), 409, "llm_disabled"),
        (recorded({LLMTask.SUGGEST_EXTRACTION_RULE: json.dumps(bad)})[0], 503, "llm_no_suggestion"),
        (recorded({LLMTask.SUGGEST_EXTRACTION_RULE: "{}"})[0], 503, "llm_no_suggestion"),
    ]
    for llm, status_code, code in cases:
        async with api_client(db, llm=llm) as client:
            response = await client.post(
                f"/sources/{source}/extraction-rules/suggest", headers=ADMIN_AUTH
            )
        assert response.status_code == status_code
        assert response.json()["type"].rsplit(":", 1)[-1] == code
    async with db.tenant_session(TENANT_A) as session:
        assert (await session.scalars(select(ExtractionRuleVersionRow))).all() == []

    async with api_client(db, llm=cases[1][0]) as client:
        expert = await client.post(
            f"/sources/{source}/extraction-rules/suggest", headers=EXPERT_AUTH
        )
    assert expert.status_code == 403


async def test_rule_suggestion_needs_samples_and_a_cleared_source(db: Database) -> None:
    llm, adapter = recorded({LLMTask.SUGGEST_EXTRACTION_RULE: json.dumps(RULE_ANSWER)})
    no_samples = await seed_source(db, TENANT_A, name="no samples")
    uncleared = await seed_source(db, TENANT_A, name="uncleared", cleared=False)
    async with api_client(db, llm=llm) as client:
        empty = await client.post(
            f"/sources/{no_samples}/extraction-rules/suggest", headers=ADMIN_AUTH
        )
        blocked = await client.post(
            f"/sources/{uncleared}/extraction-rules/suggest", headers=ADMIN_AUTH
        )
    assert (empty.status_code, empty.json()["type"].rsplit(":", 1)[-1]) == (422, "no_samples")
    assert (blocked.status_code, blocked.json()["type"].rsplit(":", 1)[-1]) == (
        409,
        "source_not_cleared",
    )
    assert adapter.calls == []


# --- 8.10 offer URL suggestion -------------------------------------------------------------

PICKS = [
    (f"{SITE}/product/ssd-samsung-990-pro-1tb", 0.95),
    (f"{SITE}/product/ssd-samsung-990-pro-1tb-heatsink", 0.7),
    (f"{SITE}/product/m2-heatsink-for-990", 0.3),  # below the confidence cut-off
]


async def _search_source(db: Database, **source: Any) -> uuid.UUID:
    source_id = await seed_source(db, TENANT_A, quota=600, **source)
    async with db.tenant_session(TENANT_A) as session:
        await config.put_config(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=source_id,
            config={"search_url_template": f"{SITE}/search?q={{query}}"},
        )
    return source_id


class Site:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, headers={"Retry-After": "120"})
        body = (FIXTURES / "generic/search_results.html").read_bytes()
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})


def _deps(
    db: Database, redis: Redis, llm: LLMService, site: Site, requeued: list[Any]
) -> UrlSuggestionDeps:
    http = HttpFetcher(user_agent="test", transport=httpx.MockTransport(site))
    return UrlSuggestionDeps(
        database=lambda: db,
        limiter=lambda: SourceRateLimiter(redis),
        http=lambda: http,
        llm=llm,
        requeue=lambda envelope, delay: requeued.append((envelope, delay)),
    )


async def _request(
    db: Database, source: uuid.UUID, variant: uuid.UUID, llm: LLMService
) -> EventEnvelope:
    async with api_client(db, llm=llm) as client:
        response = await client.post(
            f"/sources/{source}/offer-url-suggestions",
            json={"variant_id": str(variant)},
            headers=EXPERT_AUTH,
        )
    assert response.status_code == 202, response.text
    request_id = uuid.UUID(response.json()["request_id"])
    async with db.tenant_session(TENANT_A) as session:
        row = await session.get(OutboxEventRow, request_id)
    assert row is not None
    return row.envelope()


def _answer(picks: list[tuple[str, float]]) -> str:
    return json.dumps(
        {
            "candidates": [
                {"url": url, "confidence": conf, "rationale": "Same model and capacity."}
                for url, conf in picks
            ]
        }
    )


async def test_url_suggestions_are_stored_unscheduled_until_confirmed(
    db: Database, redis_client: Redis
) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await _search_source(db)
    llm, adapter = recorded({LLMTask.SUGGEST_OFFER_URLS: _answer(PICKS)})
    envelope = await _request(db, source, variant, llm)
    site = Site()
    await url_suggestion_handler(_deps(db, redis_client, llm, site, []))(envelope)

    [request] = site.requests
    assert str(request.url) == f"{SITE}/search?q=Samsung+990+PRO+1TB"
    sent = adapter.calls[0].user
    assert f"{SITE}/product/ssd-samsung-980-pro-1tb" in sent
    assert "ads.example.net" not in sent  # off-domain links are not offered to the model
    assert "evil.example.com" not in sent  # nor is comment text

    async with db.tenant_session(TENANT_A) as session:
        offers = (
            await session.scalars(select(TrackedOfferRow).order_by(TrackedOfferRow.url))
        ).all()
        [audit] = await list_events(session, action="source.offer_urls.suggested")
    assert [o.url for o in offers] == sorted(url for url, conf in PICKS if conf >= 0.5)
    assert {(o.status, o.suggested_by, o.next_due_at) for o in offers} == {
        ("suggested", "llm", None)
    }
    assert all(o.suggestion_rationale and "Same model" in o.suggestion_rationale for o in offers)
    assert audit.after is not None
    assert audit.after["outcome"] == "ok"
    assert audit.after["requested_by"] == "pilot-expert"

    assert await schedule_due(db, now=datetime.now(UTC) + timedelta(days=1)) == 0  # not scheduled
    async with api_client(db, llm=llm) as client:
        confirmed = await client.post(
            f"/tracked-offers/{offers[0].id}/review",
            json={"decision": "confirm"},
            headers=EXPERT_AUTH,
        )
    assert confirmed.json()["status"] == "active"
    assert await schedule_due(db, now=datetime.now(UTC) + timedelta(days=1)) == 1


async def test_urls_not_on_the_page_are_rejected(db: Database, redis_client: Redis) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await _search_source(db)

    def hallucinate(call: Completion) -> str:
        return _answer(
            [(f"{SITE}/product/ssd-samsung-990-pro-1tb", 0.9), ("https://evil.example.com/p", 0.9)]
        )

    llm, _ = recorded({LLMTask.SUGGEST_OFFER_URLS: hallucinate})
    envelope = await _request(db, source, variant, llm)
    await url_suggestion_handler(_deps(db, redis_client, llm, Site(), []))(envelope)
    async with db.tenant_session(TENANT_A) as session:
        assert (await session.scalars(select(TrackedOfferRow))).all() == []
        [audit] = await list_events(session, action="source.offer_urls.suggested")
    assert audit.after is not None
    assert audit.after["outcome"] == "llm_invalid"


async def test_search_fetch_respects_quota_and_blocking(db: Database, redis_client: Redis) -> None:
    variant = await seed_variant(db, TENANT_A)
    source = await _search_source(db)
    llm, adapter = recorded({LLMTask.SUGGEST_OFFER_URLS: _answer(PICKS)})
    envelope = await _request(db, source, variant, llm)

    limiter = SourceRateLimiter(redis_client)
    await limiter.pause(TENANT_A, source, 60)
    requeued: list[Any] = []
    site = Site()
    await url_suggestion_handler(_deps(db, redis_client, llm, site, requeued))(envelope)
    assert site.requests == []  # paused: no request sent, the job is deferred
    assert requeued
    assert requeued[0][1] >= 1_000

    await redis_client.flushdb()
    blocked = Site(status=403)
    await url_suggestion_handler(_deps(db, redis_client, llm, blocked, []))(envelope)
    assert await limiter.paused_for_ms(TENANT_A, source) > 0
    assert adapter.calls == []
    async with db.tenant_session(TENANT_A) as session:
        [audit] = await list_events(session, action="source.offer_urls.suggested")
    assert audit.after is not None
    assert audit.after["outcome"] == "fetch_failed:blocked"


async def test_url_suggestion_requests_are_validated(db: Database) -> None:
    variant = await seed_variant(db, TENANT_A)
    llm, _ = recorded({})
    uncleared = await seed_source(db, TENANT_A, name="uncleared", cleared=False)
    no_template = await seed_source(db, TENANT_A, name="no template")
    rendered = await _search_source(db, name="rendered", method="rendered_page")
    async with api_client(db, llm=llm) as client:
        results = {}
        for name, source in (
            ("uncleared", uncleared),
            ("no_template", no_template),
            ("rendered", rendered),
        ):
            response = await client.post(
                f"/sources/{source}/offer-url-suggestions",
                json={"variant_id": str(variant)},
                headers=EXPERT_AUTH,
            )
            results[name] = (response.status_code, response.json()["type"].rsplit(":", 1)[-1])
    assert results == {
        "uncleared": (409, "source_not_cleared"),
        "no_template": (422, "no_search_url"),
        "rendered": (409, "search_not_supported"),
    }
