"""Connector runtime: the single path every automated fetch takes (tasks 4.11, 4.5).

Scheduled fetches, on-demand re-checks and qualification runs all call :func:`run_fetch`. It
refuses to contact a source unless the source is collectable and holds an unrevoked clearance,
takes a slot from the source's rate limiter, pauses the source on ``blocked`` responses that
carry ``Retry-After``, and only then calls the connector.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.core.correlation import get_correlation_id
from pricing_assistant.core.crypto import SecretBox
from pricing_assistant.core.logging import get_logger
from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.config import decrypted_secrets, get_config
from pricing_assistant.sources.connector import (
    ExtractionRule,
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    OfferTarget,
)
from pricing_assistant.sources.connectors.registry import ConnectorRegistry
from pricing_assistant.sources.models import (
    ExtractionRuleVersionRow,
    RetrievalMethod,
    RuleVersionState,
    SourceRow,
    TrackedOfferRow,
)
from pricing_assistant.sources.ratelimit import SourceRateLimiter
from pricing_assistant.sources.registry import may_fetch

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PreparedFetch:
    source: SourceRow
    target: OfferTarget
    context: FetchContext


async def active_rule(session: AsyncSession, source_id: uuid.UUID) -> ExtractionRule | None:
    row = await session.scalar(
        select(ExtractionRuleVersionRow).where(
            ExtractionRuleVersionRow.source_id == source_id,
            ExtractionRuleVersionRow.state == RuleVersionState.ACTIVE.value,
        )
    )
    return ExtractionRule(version_id=row.id, config=row.config) if row else None


async def prepare_fetch(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    tracked_offer_id: uuid.UUID,
    box: SecretBox,
    user_agent: str,
    timeout_seconds: float,
) -> PreparedFetch | FetchFailure:
    """Clearance gate plus everything a connector needs, read in the caller's transaction."""
    offer = await session.get(TrackedOfferRow, tracked_offer_id)
    if offer is None:
        return FetchFailure(FetchErrorClass.CONFIGURATION, "tracked offer not found")
    source = await session.get(SourceRow, offer.source_id)
    if source is None or not await may_fetch(session, source):
        return FetchFailure(
            FetchErrorClass.CLEARANCE_MISSING,
            "source is not cleared for automated collection",
        )
    target = OfferTarget(
        tracked_offer_id=offer.id,
        source_id=source.id,
        variant_id=offer.variant_id,
        url=offer.url,
        external_id=offer.external_id,
        currency_unit=CurrencyUnit(source.currency_unit),
        base_domain=source.base_domain,
        is_own_store=offer.is_own_store,
        is_own_channel=offer.is_own_channel,
    )
    context = FetchContext(
        tenant_id=tenant_id,
        correlation_id=get_correlation_id(),
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        extraction_rule=await active_rule(session, source.id),
        connector_config=await get_config(session, source.id),
        secrets=await decrypted_secrets(session, box, tenant_id, source.id),
    )
    return PreparedFetch(source=source, target=target, context=context)


async def run_fetch(
    prepared: PreparedFetch | FetchFailure,
    *,
    limiter: SourceRateLimiter,
    connectors: ConnectorRegistry,
    slot_reserved: bool = False,
) -> FetchResult:
    """Acquire a quota slot and fetch. Never contacts a source the gate refused.

    ``slot_reserved`` is set when the slot was already taken when the request was accepted
    (on-demand re-checks), so it is not counted twice.
    """
    if isinstance(prepared, FetchFailure):
        return prepared
    source, target, ctx = prepared.source, prepared.target, prepared.context
    admission = (
        None
        if slot_reserved
        else await limiter.acquire(ctx.tenant_id, source.id, source.quota_per_minute)
    )
    if admission is not None and not admission.granted:
        return FetchFailure(
            FetchErrorClass.QUOTA_EXHAUSTED,
            "source paused" if admission.paused else "source quota exhausted",
            retry_after_seconds=max(1, admission.retry_after_ms // 1000),
        )
    connector = connectors.connector_for(source.connector_key, RetrievalMethod(source.method))
    result = await connector.fetch(target, ctx)
    if isinstance(result, FetchFailure) and result.error_class is FetchErrorClass.BLOCKED:
        pause = result.retry_after_seconds or 15 * 60
        await limiter.pause(ctx.tenant_id, source.id, pause)
        log.warning(
            "source.blocked",
            source_id=str(source.id),
            http_status=result.http_status,
            pause_seconds=pause,
        )
    return result
