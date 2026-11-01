"""Tracked offers: registering, suggesting, confirming and dismissing offer URLs (task 4.9).

URLs may be registered only on cleared sources in ``under_evaluation`` or ``approved`` and only
within the source's domain. Suggested URLs (from search or the language model) are not
scheduled until an expert or admin confirms them.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.catalog.api import variant_exists
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.events import TrackedOfferActivated
from pricing_assistant.sources.http_fetcher import host_allowed
from pricing_assistant.sources.models import (
    SourceRow,
    SourceStatus,
    TrackedOfferRow,
    TrackedOfferStatus,
)
from pricing_assistant.sources.registry import COLLECTABLE, current_clearance, get_source


async def _check_source_and_url(session: AsyncSession, source: SourceRow, url: str) -> None:
    if (
        SourceStatus(source.status) not in COLLECTABLE
        or await current_clearance(session, source.id) is None
    ):
        raise Conflict(
            "Offers can be tracked only on cleared sources under evaluation or approved",
            code="source_not_trackable",
            message_fa=(
                "فقط در منابع دارای مجوز که در حال ارزیابی یا تأییدشده‌اند می‌توان پیشنهاد ثبت کرد."
            ),
        )
    if not host_allowed(url, source.base_domain):
        raise ValidationFailed(
            f"URL must be on {source.base_domain}",
            code="url_outside_source",
            message_fa=f"نشانی باید در دامنه {source.base_domain} باشد.",
        )


async def _duplicate(
    session: AsyncSession, source_id: uuid.UUID, url: str, variant_id: uuid.UUID
) -> TrackedOfferRow | None:
    row: TrackedOfferRow | None = await session.scalar(
        select(TrackedOfferRow).where(
            TrackedOfferRow.source_id == source_id,
            TrackedOfferRow.url == url,
            TrackedOfferRow.variant_id == variant_id,
        )
    )
    return row


async def register_offer(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    variant_id: uuid.UUID,
    url: str,
    external_id: str | None = None,
    is_own_store: bool = False,
    is_own_channel: bool = False,
) -> TrackedOfferRow:
    source = await get_source(session, source_id)
    await _check_source_and_url(session, source, url)
    if not await variant_exists(session, variant_id):
        raise NotFound("Variant not found", message_fa="کالا یافت نشد.")
    if await _duplicate(session, source_id, url, variant_id):
        raise Conflict(
            "This URL is already tracked for the variant", message_fa="این نشانی قبلاً ثبت شده است."
        )
    offer = TrackedOfferRow(
        id=new_id(),
        tenant_id=tenant_id,
        source_id=source_id,
        variant_id=variant_id,
        url=url,
        external_id=external_id,
        status=TrackedOfferStatus.ACTIVE.value,
        is_own_store=is_own_store,
        is_own_channel=is_own_channel,
        next_due_at=datetime.now(UTC),
        created_by=actor.username,
        confirmed_by=actor.username,
        confirmed_at=datetime.now(UTC),
    )
    session.add(offer)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=TrackedOfferActivated(tracked_offer_id=offer.id, variant_id=variant_id),
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.offer.registered",
        target_type="tracked_offer",
        target_id=offer.id,
        after={
            "url": url,
            "variant_id": str(variant_id),
            "source_id": str(source_id),
            "own_store": is_own_store,
            "own_channel": is_own_channel,
        },
    )
    return offer


async def suggest_offer(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    suggested_by: str,
    source_id: uuid.UUID,
    variant_id: uuid.UUID,
    url: str,
    rationale: str | None,
) -> TrackedOfferRow | None:
    """Store a suggestion (no schedule). Returns None if the URL is already known."""
    source = await get_source(session, source_id)
    await _check_source_and_url(session, source, url)
    if await _duplicate(session, source_id, url, variant_id):
        return None
    offer = TrackedOfferRow(
        id=new_id(),
        tenant_id=tenant_id,
        source_id=source_id,
        variant_id=variant_id,
        url=url,
        status=TrackedOfferStatus.SUGGESTED.value,
        suggested_by=suggested_by,
        suggestion_rationale=rationale,
        created_by=suggested_by,
    )
    session.add(offer)
    await session.flush()
    return offer


async def review_suggestion(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    tracked_offer_id: uuid.UUID,
    confirm: bool,
    reason: str | None = None,
) -> TrackedOfferRow:
    offer = await session.get(TrackedOfferRow, tracked_offer_id, with_for_update=True)
    if offer is None:
        raise NotFound("Tracked offer not found", message_fa="پیشنهاد یافت نشد.")
    if offer.status != TrackedOfferStatus.SUGGESTED.value:
        raise Conflict(
            "Only suggestions can be confirmed or dismissed", message_fa="این مورد پیشنهادی نیست."
        )
    if confirm:
        source = await get_source(session, offer.source_id)
        await _check_source_and_url(session, source, offer.url)
        offer.status = TrackedOfferStatus.ACTIVE.value
        offer.next_due_at = datetime.now(UTC)
        offer.confirmed_by = actor.username
        offer.confirmed_at = datetime.now(UTC)
        await publish(
            session,
            tenant_id=tenant_id,
            event=TrackedOfferActivated(tracked_offer_id=offer.id, variant_id=offer.variant_id),
        )
    else:
        offer.status = TrackedOfferStatus.DISMISSED.value
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.offer.confirmed" if confirm else "source.offer.dismissed",
        target_type="tracked_offer",
        target_id=offer.id,
        before={"status": TrackedOfferStatus.SUGGESTED.value},
        after={"status": offer.status, "url": offer.url, "suggested_by": offer.suggested_by},
        reason=reason,
    )
    return offer


async def set_paused(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    tracked_offer_id: uuid.UUID,
    paused: bool,
    reason: str,
) -> TrackedOfferRow:
    offer = await session.get(TrackedOfferRow, tracked_offer_id, with_for_update=True)
    if offer is None:
        raise NotFound("Tracked offer not found", message_fa="پیشنهاد یافت نشد.")
    expected = TrackedOfferStatus.ACTIVE if paused else TrackedOfferStatus.PAUSED
    if offer.status != expected.value:
        raise Conflict(f"Offer is not {expected.value}")
    offer.status = (TrackedOfferStatus.PAUSED if paused else TrackedOfferStatus.ACTIVE).value
    if not paused:
        offer.next_due_at = datetime.now(UTC)
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.offer.paused" if paused else "source.offer.resumed",
        target_type="tracked_offer",
        target_id=offer.id,
        reason=reason,
    )
    return offer


async def offers_for_variant(session: AsyncSession, variant_id: uuid.UUID) -> list[TrackedOfferRow]:
    rows = await session.scalars(
        select(TrackedOfferRow)
        .where(TrackedOfferRow.variant_id == variant_id)
        .order_by(TrackedOfferRow.created_at)
    )
    return list(rows.all())
