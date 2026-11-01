"""On-demand re-check of a single tracked offer (task 5.7).

A re-check is accepted only if the expert still has daily budget and the source has a free
quota slot right now; the slot is taken when the request is accepted, so the worker does not
count it again. Otherwise the request is refused with the time of the next free slot, and no
request is sent to the source.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.collection.models import FetchTrigger, RecheckRequestRow, RecheckStatus
from pricing_assistant.collection.scheduling import request_for
from pricing_assistant.core import tenant_settings
from pricing_assistant.core.errors import Conflict, NotFound, TooManyRequests
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.sources.api import (
    RecheckBudget,
    SourceRateLimiter,
    SourceRow,
    TrackedOfferRow,
    TrackedOfferStatus,
    may_fetch,
)

TEHRAN = ZoneInfo("Asia/Tehran")


def _clock_fa(when: datetime) -> str:
    return when.astimezone(TEHRAN).strftime("%H:%M:%S")


async def request_recheck(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    tracked_offer_id: uuid.UUID,
    limiter: SourceRateLimiter,
    budget: RecheckBudget,
    now: datetime | None = None,
) -> RecheckRequestRow:
    now = now or datetime.now(UTC)
    offer = await session.get(TrackedOfferRow, tracked_offer_id)
    if offer is None or offer.status != TrackedOfferStatus.ACTIVE.value:
        raise NotFound("Tracked offer not found or not active", message_fa="پیشنهاد فعال یافت نشد.")
    source = await session.get(SourceRow, offer.source_id)
    if source is None or not await may_fetch(session, source):
        raise Conflict(
            "Source is not cleared for automated collection",
            code="clearance_missing",
            message_fa="مجوز جمع‌آوری خودکار این منبع ثبت یا فعال نیست.",
        )
    settings = await tenant_settings.load(session, tenant_id)
    allowed, remaining = await budget.try_consume(
        tenant_id, actor.subject, settings.recheck_daily_budget_per_user, now=now
    )
    if not allowed:
        raise TooManyRequests(
            "Daily re-check budget used up",
            code="recheck_budget_exhausted",
            message_fa=(
                f"سقف روزانه بررسی مجدد ({settings.recheck_daily_budget_per_user}) "
                "برای شما پر شده است."
            ),
        )
    admission = await limiter.acquire(tenant_id, source.id, source.quota_per_minute)
    if not admission.granted:
        await budget.refund(tenant_id, actor.subject, now=now)
        retry_at = now + timedelta(milliseconds=admission.retry_after_ms)
        seconds = max(1, -(-admission.retry_after_ms // 1000))
        raise TooManyRequests(
            "Source quota is exhausted for now",
            code="source_quota_exhausted",
            message_fa=f"سقف درخواست این منبع فعلاً پر است؛ از ساعت {_clock_fa(retry_at)} دوباره تلاش کنید.",
            extra={"retry_at": retry_at.isoformat(), "paused": admission.paused},
            headers={"Retry-After": str(seconds)},
        )
    recheck = RecheckRequestRow(
        id=new_id(),
        tenant_id=tenant_id,
        tracked_offer_id=offer.id,
        requested_by=actor.username,
        status=RecheckStatus.PENDING.value,
    )
    session.add(recheck)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=request_for(
            source,
            tracked_offer_id=offer.id,
            window_start=now,
            trigger=FetchTrigger.RECHECK.value,
            recheck_id=recheck.id,
            slot_reserved=True,
        ),
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="collection.recheck.requested",
        target_type="tracked_offer",
        target_id=offer.id,
        after={"recheck_id": str(recheck.id), "remaining_today": remaining},
    )
    return recheck
