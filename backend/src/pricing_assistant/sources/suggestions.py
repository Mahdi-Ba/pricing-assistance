"""LLM-assisted suggestions for sources (tasks 8.9, 8.10).

Both features only *propose*; nothing is used until a human approves it:

- :func:`suggest_extraction_rule` sends a source's stored sample pages (public content, compacted)
  to the model and stores the answer as a ``proposed`` extraction rule version, validated on the
  same samples. Only an admin approval activates it (task 4.12).
- :func:`handle_url_suggestion` (worker, ``collect`` queue) fetches the source's search-results
  page through the normal clearance gate and quota, sends its on-domain links to the model and
  stores the chosen ones as ``suggested`` tracked offers. Suggestions are never scheduled; an
  expert confirms them first. The model never fetches anything itself, and every URL it returns
  must be one of the links on the fetched page.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import quote_plus, urldefrag, urljoin

from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser

from pricing_assistant.audit.api import SYSTEM_ACTOR, AuditActor, record
from pricing_assistant.catalog.api import VariantInfo, get_variant
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import EventEnvelope, publish
from pricing_assistant.core.logging import get_logger
from pricing_assistant.llm.api import (
    MAX_PAGE_CHARS,
    PUBLIC_ATTRIBUTE_KEYS,
    CandidateVariant,
    LLMPort,
    PageContent,
    RuleRequest,
    RuleSuggestion,
    UrlRequest,
    UrlSuggestions,
    require_value,
)
from pricing_assistant.sources.config import get_config
from pricing_assistant.sources.connector import FetchErrorClass, FetchFailure
from pricing_assistant.sources.events import OfferUrlSuggestionRequested
from pricing_assistant.sources.extraction import parse_rule
from pricing_assistant.sources.http_fetcher import HttpFetcher, host_allowed
from pricing_assistant.sources.models import (
    ExtractionRuleVersionRow,
    RetrievalMethod,
    RuleOrigin,
    SourceRow,
    TrackedOfferRow,
)
from pricing_assistant.sources.offers import suggest_offer
from pricing_assistant.sources.ratelimit import SourceRateLimiter
from pricing_assistant.sources.registry import get_source, may_fetch
from pricing_assistant.sources.rules import propose_rule, samples

log = get_logger(__name__)

MAX_RULE_SAMPLES = 3
MAX_LINKS = 200
MIN_URL_CONFIDENCE = 0.5
SEARCH_TEMPLATE_KEY = "search_url_template"
_DROP = "script, style, noscript, svg, iframe, link, meta, template, head"
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SPACE = re.compile(r"\s+")


def compact_html(html: str, limit: int = MAX_PAGE_CHARS) -> str:
    """Page markup without scripts, styles, comments and inline styles, whitespace collapsed."""
    tree = LexborHTMLParser(html)
    for node in tree.css(_DROP):
        node.decompose()
    body = tree.body
    if body is None:
        return ""
    for node in body.traverse():
        if node.attributes.get("style") is not None:
            del node.attrs["style"]
    markup = _SPACE.sub(" ", _COMMENT.sub("", body.html or ""))
    return markup[:limit]


def page_links(html: str, page_url: str, base_domain: str) -> list[tuple[str, str]]:
    """Distinct absolute on-domain links with their visible text, in page order."""
    seen: dict[str, str] = {}
    for anchor in LexborHTMLParser(html).css("a[href]"):
        href = anchor.attributes.get("href") or ""
        url, _ = urldefrag(urljoin(page_url, href.strip()))
        if not host_allowed(url, base_domain) or url in seen:
            continue
        seen[url] = _SPACE.sub(" ", anchor.text(strip=True))[:200]
        if len(seen) >= MAX_LINKS:
            break
    return list(seen.items())


# --- 8.9 extraction rule suggestion --------------------------------------------------------


def _rule_check(value: BaseModel) -> str | None:
    assert isinstance(value, RuleSuggestion)  # noqa: S101 - the port validated the type
    try:
        parse_rule(value.to_rule_config())
    except ValueError:
        return "not a valid selector rule"
    return None


async def suggest_extraction_rule(
    db: Database,
    llm: LLMPort,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
) -> ExtractionRuleVersionRow:
    """Ask the model for a selector rule; store it as ``proposed`` with its sample results."""
    async with db.tenant_session(tenant_id) as session:
        source = await get_source(session, source_id)
        if not await may_fetch(session, source):
            raise Conflict(
                "Rule suggestions need a cleared source",
                code="source_not_cleared",
                message_fa="فقط برای منابع دارای مجوز می‌توان قاعده پیشنهاد گرفت.",
            )
        pages = await samples(session, source_id)
        if not pages:
            raise ValidationFailed(
                "Add sample pages to the source first",
                code="no_samples",
                message_fa="ابتدا صفحه‌های نمونه این منبع را بارگذاری کنید.",
            )
        contents = [
            PageContent(url=p.url, content=compact_html(p.html()))
            for p in pages[-MAX_RULE_SAMPLES:]
        ]
    # the model call runs outside any database transaction
    result = await llm.suggest_extraction_rule(
        tenant_id, RuleRequest(samples=contents), check=_rule_check
    )
    suggestion = require_value(result)
    async with db.tenant_session(tenant_id) as session:
        version = await propose_rule(
            session,
            tenant_id=tenant_id,
            actor=actor,
            source_id=source_id,
            config=suggestion.to_rule_config(),
            origin=RuleOrigin.LLM,
        )
        await record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="source.extraction_rule.suggested",
            target_type="extraction_rule_version",
            target_id=version.id,
            after={"version": version.version, "rationale": suggestion.rationale},
        )
        return version


# --- 8.10 offer URL suggestion -------------------------------------------------------------


def _search_template(source: SourceRow, config: dict[str, object]) -> str:
    template = config.get(SEARCH_TEMPLATE_KEY)
    if (
        not isinstance(template, str)
        or "{query}" not in template
        or not host_allowed(template.replace("{query}", "x"), source.base_domain)
    ):
        raise ValidationFailed(
            f"The source needs a '{SEARCH_TEMPLATE_KEY}' on {source.base_domain} with {{query}}",
            code="no_search_url",
            message_fa="برای این منبع نشانی جست‌وجو تعریف نشده است.",
        )
    return template


async def request_url_suggestions(
    db: Database,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> uuid.UUID:
    """Validate and enqueue a suggestion job; returns its request (event) ID."""
    async with db.tenant_session(tenant_id) as session:
        source = await get_source(session, source_id)
        if not await may_fetch(session, source):
            raise Conflict(
                "URL suggestions need a cleared source",
                code="source_not_cleared",
                message_fa="فقط در منابع دارای مجوز می‌توان نشانی پیشنهاد گرفت.",
            )
        if RetrievalMethod(source.method) is not RetrievalMethod.HTML:
            raise Conflict(
                "URL suggestions are available for HTML sources only",
                code="search_not_supported",
                message_fa="پیشنهاد نشانی فقط برای منابع HTML پشتیبانی می‌شود.",
            )
        _search_template(source, await get_config(session, source_id))
        if await get_variant(session, variant_id) is None:
            raise NotFound("Variant not found", message_fa="کالا یافت نشد.")
        envelope = await publish(
            session,
            tenant_id=tenant_id,
            event=OfferUrlSuggestionRequested(
                source_id=source_id, variant_id=variant_id, requested_by=actor.username
            ),
        )
        await record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="source.offer_urls.requested",
            target_type="source",
            target_id=source_id,
            after={"variant_id": str(variant_id), "request_id": str(envelope.event_id)},
        )
        return envelope.event_id


@dataclass(frozen=True, slots=True)
class UrlSuggestionDeps:
    database: Callable[[], Database]
    limiter: Callable[[], SourceRateLimiter]
    http: Callable[[], HttpFetcher]
    llm: LLMPort
    requeue: Callable[[EventEnvelope, int], None]


@dataclass(frozen=True, slots=True)
class _Plan:
    source_id: uuid.UUID
    base_domain: str
    quota_per_minute: int
    search_url: str
    variant: CandidateVariant


def _candidate(variant: VariantInfo) -> CandidateVariant:
    public = {
        k: v
        for k, v in variant.attributes.items()
        if k in PUBLIC_ATTRIBUTE_KEYS and isinstance(v, str | int) and not isinstance(v, bool)
    }
    return CandidateVariant(
        id=variant.id,
        brand=variant.brand,
        model=variant.model,
        name=variant.product_name,
        attributes=public,
    )


async def _plan(db: Database, envelope: EventEnvelope) -> _Plan | str:
    event = envelope.decode(OfferUrlSuggestionRequested)
    async with db.tenant_session(envelope.tenant_id) as session:
        source = await session.get(SourceRow, event.source_id)
        if source is None or not await may_fetch(session, source):
            return "source_not_cleared"
        variant = await get_variant(session, event.variant_id)
        if variant is None:
            return "variant_not_found"
        try:
            template = _search_template(source, await get_config(session, source.id))
        except ValidationFailed:
            return "no_search_url"
        capacity = variant.attributes.get("capacity")
        query = " ".join(str(p) for p in (variant.brand, variant.model, capacity) if p)
        return _Plan(
            source_id=source.id,
            base_domain=source.base_domain,
            quota_per_minute=source.quota_per_minute,
            search_url=template.replace("{query}", quote_plus(query)),
            variant=_candidate(variant),
        )


async def _finish(
    db: Database,
    envelope: EventEnvelope,
    *,
    outcome: str,
    created: list[TrackedOfferRow] | None = None,
) -> None:
    event = envelope.decode(OfferUrlSuggestionRequested)
    async with db.tenant_session(envelope.tenant_id) as session:
        await record(
            session,
            tenant_id=envelope.tenant_id,
            actor=SYSTEM_ACTOR,
            action="source.offer_urls.suggested",
            target_type="source",
            target_id=event.source_id,
            after={
                "request_id": str(envelope.event_id),
                "requested_by": event.requested_by,
                "variant_id": str(event.variant_id),
                "outcome": outcome,
                "suggested": [str(o.id) for o in created or []],
            },
        )
    log.info("sources.offer_urls_suggested", outcome=outcome, count=len(created or []))


def url_suggestion_handler(deps: UrlSuggestionDeps) -> Callable[[EventEnvelope], Awaitable[None]]:
    async def handle(envelope: EventEnvelope) -> None:
        db = deps.database()
        plan = await _plan(db, envelope)
        if isinstance(plan, str):
            await _finish(db, envelope, outcome=plan)
            return
        limiter = deps.limiter()
        admission = await limiter.acquire(envelope.tenant_id, plan.source_id, plan.quota_per_minute)
        if not admission.granted:
            deps.requeue(envelope, max(1_000, admission.retry_after_ms))
            return
        page = await deps.http().get(plan.search_url, base_domain=plan.base_domain)
        if isinstance(page, FetchFailure):
            if page.error_class is FetchErrorClass.BLOCKED:
                await limiter.pause(
                    envelope.tenant_id, plan.source_id, page.retry_after_seconds or 15 * 60
                )
            await _finish(db, envelope, outcome=f"fetch_failed:{page.error_class.value}")
            return
        html = page.body.decode("utf-8", errors="replace")
        links = page_links(html, page.url, plan.base_domain)
        if not links:
            await _finish(db, envelope, outcome="no_links")
            return
        listed = {url for url, _ in links}
        content = "\n".join(f"{url} | {text}" for url, text in links)[:MAX_PAGE_CHARS]

        def on_page(value: BaseModel) -> str | None:
            assert isinstance(value, UrlSuggestions)  # noqa: S101 - the port validated the type
            if any(c.url not in listed for c in value.candidates):
                return "a suggested URL is not a link on the fetched page"
            return None

        result = await deps.llm.suggest_offer_urls(
            envelope.tenant_id,
            UrlRequest(
                variant=plan.variant, search_page=PageContent(url=page.url, content=content)
            ),
            check=on_page,
        )
        if not result.ok or result.value is None:
            await _finish(db, envelope, outcome=f"llm_{result.outcome.value}")
            return
        created: list[TrackedOfferRow] = []
        async with db.tenant_session(envelope.tenant_id) as session:
            for candidate in result.value.candidates:
                if candidate.confidence < MIN_URL_CONFIDENCE:
                    continue
                row = await suggest_offer(
                    session,
                    tenant_id=envelope.tenant_id,
                    suggested_by="llm",
                    source_id=plan.source_id,
                    variant_id=plan.variant.id,
                    url=candidate.url,
                    rationale=f"{candidate.rationale} (اطمینان {candidate.confidence:.2f})",
                )
                if row is not None:
                    created.append(row)
        await _finish(db, envelope, outcome="ok", created=created)

    return handle
