"""Source registry rules: lifecycle, access clearance and quotas (tasks 4.2, 4.11).

- A source may be fetched automatically only while it has an unrevoked clearance and is
  ``under_evaluation`` or ``approved``.
- Only ``approved`` sources feed recommendations.
- The request quota never exceeds the clearance's permitted rate.
- Revoking a clearance suspends the source.
- Domain, retrieval method, connector and currency unit change only while the source is not
  collecting; the domain also not once offers are tracked on it.
- Only a candidate that was never used (no clearance, offer, rule, sample or collected data) may
  be deleted; any other source is rejected or suspended instead, so its history stays traceable.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.events import SourceStatusChanged
from pricing_assistant.sources.models import (
    ClearanceKind,
    RetrievalMethod,
    SourceClearanceRow,
    SourceRow,
    SourceStatus,
    TrackedOfferRow,
)

COLLECTABLE = frozenset({SourceStatus.UNDER_EVALUATION, SourceStatus.APPROVED})
NEEDS_CLEARANCE = COLLECTABLE

TRANSITIONS: dict[SourceStatus, frozenset[SourceStatus]] = {
    SourceStatus.CANDIDATE: frozenset({SourceStatus.UNDER_EVALUATION, SourceStatus.REJECTED}),
    SourceStatus.UNDER_EVALUATION: frozenset(
        {SourceStatus.APPROVED, SourceStatus.REJECTED, SourceStatus.SUSPENDED}
    ),
    SourceStatus.APPROVED: frozenset({SourceStatus.SUSPENDED}),
    SourceStatus.SUSPENDED: frozenset(
        {SourceStatus.APPROVED, SourceStatus.UNDER_EVALUATION, SourceStatus.REJECTED}
    ),
    SourceStatus.REJECTED: frozenset({SourceStatus.CANDIDATE}),
}


@dataclass(frozen=True, slots=True)
class SourceSettings:
    quota_per_minute: int
    interval_a_seconds: int
    interval_b_seconds: int
    interval_c_seconds: int


def feeds_recommendations(status: str) -> bool:
    return status == SourceStatus.APPROVED.value


async def current_clearance(
    session: AsyncSession, source_id: uuid.UUID
) -> SourceClearanceRow | None:
    """The clearance in force: the newest record if it is a grant, otherwise None."""
    latest: SourceClearanceRow | None = await session.scalar(
        select(SourceClearanceRow)
        .where(SourceClearanceRow.source_id == source_id)
        .order_by(SourceClearanceRow.created_at.desc(), SourceClearanceRow.id.desc())
        .limit(1)
    )
    if latest is None or latest.kind != ClearanceKind.GRANTED.value:
        return None
    return latest


async def may_fetch(session: AsyncSession, source: SourceRow) -> bool:
    """Clearance gate: automated fetches need a collectable status and a clearance in force."""
    if SourceStatus(source.status) not in COLLECTABLE:
        return False
    return await current_clearance(session, source.id) is not None


async def get_source(
    session: AsyncSession, source_id: uuid.UUID, *, lock: bool = False
) -> SourceRow:
    source = await session.get(SourceRow, source_id, with_for_update=lock)
    if source is None:
        raise NotFound("Source not found", message_fa="منبع یافت نشد.")
    return source


def _require_reason(reason: str) -> None:
    if not reason.strip():
        raise ValidationFailed("A reason is required", message_fa="دلیل را وارد کنید.")


def _check_quota(quota: int, clearance: SourceClearanceRow | None) -> None:
    permitted = clearance.permitted_requests_per_minute if clearance else None
    if permitted is not None and quota > permitted:
        raise ValidationFailed(
            f"Quota {quota}/min exceeds the permitted rate of {permitted}/min",
            code="quota_above_permitted_rate",
            message_fa=(
                f"سقف درخواست ({quota} در دقیقه) از نرخ مجاز منبع ({permitted} در دقیقه) بیشتر است."
            ),
            extra={"permitted_requests_per_minute": permitted},
        )


async def create_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    name: str,
    base_domain: str,
    connector_key: str,
    method: RetrievalMethod,
    currency_unit: CurrencyUnit,
    settings: SourceSettings,
) -> SourceRow:
    if await session.scalar(select(SourceRow.id).where(SourceRow.name == name)):
        raise Conflict("A source with this name exists", message_fa="منبعی با این نام وجود دارد.")
    source = SourceRow(
        id=new_id(),
        tenant_id=tenant_id,
        name=name,
        base_domain=base_domain.lower(),
        connector_key=connector_key,
        method=method.value,
        currency_unit=currency_unit.value,
        quota_per_minute=settings.quota_per_minute,
        interval_a_seconds=settings.interval_a_seconds,
        interval_b_seconds=settings.interval_b_seconds,
        interval_c_seconds=settings.interval_c_seconds,
        status=SourceStatus.CANDIDATE.value,
        created_by=actor.username,
    )
    session.add(source)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.created",
        target_type="source",
        target_id=source.id,
        after={"name": name, "base_domain": source.base_domain, "method": method.value},
    )
    return source


async def update_settings(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    settings: SourceSettings,
) -> SourceRow:
    source = await get_source(session, source_id, lock=True)
    _check_quota(settings.quota_per_minute, await current_clearance(session, source_id))
    before = {
        "quota_per_minute": source.quota_per_minute,
        "intervals": [
            source.interval_a_seconds,
            source.interval_b_seconds,
            source.interval_c_seconds,
        ],
    }
    source.quota_per_minute = settings.quota_per_minute
    source.interval_a_seconds = settings.interval_a_seconds
    source.interval_b_seconds = settings.interval_b_seconds
    source.interval_c_seconds = settings.interval_c_seconds
    source.updated_at = datetime.now(UTC)
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.settings.changed",
        target_type="source",
        target_id=source.id,
        before=before,
        after={
            "quota_per_minute": settings.quota_per_minute,
            "intervals": [
                settings.interval_a_seconds,
                settings.interval_b_seconds,
                settings.interval_c_seconds,
            ],
        },
    )
    return source


@dataclass(frozen=True, slots=True)
class SourceChanges:
    """Requested edits; ``None`` leaves a field unchanged."""

    name: str | None = None
    base_domain: str | None = None
    connector_key: str | None = None
    method: RetrievalMethod | None = None
    currency_unit: CurrencyUnit | None = None
    settings: SourceSettings | None = None


async def update_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    changes: SourceChanges,
) -> SourceRow:
    """Edit a source's registry entry; every change is audited with its previous value."""
    source = await get_source(session, source_id, lock=True)
    requested: dict[str, object] = {
        "name": changes.name,
        "base_domain": changes.base_domain.lower() if changes.base_domain else None,
        "connector_key": changes.connector_key,
        "method": changes.method.value if changes.method else None,
        "currency_unit": changes.currency_unit.value if changes.currency_unit else None,
    }
    if changes.settings is not None:
        requested |= {
            "quota_per_minute": changes.settings.quota_per_minute,
            "interval_a_seconds": changes.settings.interval_a_seconds,
            "interval_b_seconds": changes.settings.interval_b_seconds,
            "interval_c_seconds": changes.settings.interval_c_seconds,
        }
    changed = {k: v for k, v in requested.items() if v is not None and getattr(source, k) != v}
    if not changed:
        return source

    structural = changed.keys() & {"base_domain", "connector_key", "method", "currency_unit"}
    if structural and SourceStatus(source.status) in COLLECTABLE:
        raise Conflict(
            "Collection settings cannot change while the source is collecting",
            code="source_collecting",
            message_fa=(
                "دامنه، روش دریافت، کلید رابط و واحد پول را فقط وقتی می‌توان تغییر داد که منبع "
                "در حال دریافت نباشد؛ ابتدا منبع را «معلق» کنید."
            ),
        )
    if "base_domain" in changed and await session.scalar(
        select(TrackedOfferRow.id).where(TrackedOfferRow.source_id == source_id).limit(1)
    ):
        raise Conflict(
            "The domain of a source with tracked offers cannot change",
            code="source_has_offers",
            message_fa="برای این منبع آگهی پایش‌شده ثبت شده است؛ دامنه قابل تغییر نیست. منبع تازه‌ای بسازید.",
        )
    if "name" in changed and await session.scalar(
        select(SourceRow.id).where(SourceRow.name == changed["name"], SourceRow.id != source_id)
    ):
        raise Conflict("A source with this name exists", message_fa="منبعی با این نام وجود دارد.")
    if changes.settings is not None and "quota_per_minute" in changed:
        clearance = await current_clearance(session, source_id)
        _check_quota(changes.settings.quota_per_minute, clearance)

    before = {k: getattr(source, k) for k in changed}
    for key, value in changed.items():
        setattr(source, key, value)
    source.updated_at = datetime.now(UTC)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.updated",
        target_type="source",
        target_id=source.id,
        before=before,
        after=changed,
    )
    return source


async def delete_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    reason: str,
) -> None:
    """Delete a never-used candidate (for example one registered by mistake)."""
    _require_reason(reason)
    source = await get_source(session, source_id, lock=True)
    if source.status != SourceStatus.CANDIDATE.value:
        raise Conflict(
            "Only a candidate source can be deleted",
            code="source_not_deletable",
            message_fa=(
                "فقط منبع «نامزد» که هنوز استفاده نشده قابل حذف است؛ برای منابع دیگر وضعیت "
                "«ردشده» یا «معلق» را انتخاب کنید تا سابقه آن‌ها حفظ شود."
            ),
        )
    snapshot = {
        "name": source.name,
        "base_domain": source.base_domain,
        "connector_key": source.connector_key,
        "method": source.method,
        "currency_unit": source.currency_unit,
        "quota_per_minute": source.quota_per_minute,
    }
    try:
        # every reference to a source is a foreign key without cascade: in use means refused
        async with session.begin_nested():
            await session.delete(source)
            await session.flush()
    except IntegrityError as exc:
        raise Conflict(
            "The source is referenced by clearances, offers, rules or collected data",
            code="source_in_use",
            message_fa=(
                "این منبع سابقه دارد (مجوز، آگهی، قاعده یا داده دریافت‌شده) و قابل حذف نیست؛ "
                "وضعیت آن را «ردشده» یا «معلق» کنید."
            ),
        ) from exc
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.deleted",
        target_type="source",
        target_id=source_id,
        before=snapshot,
        reason=reason,
    )


async def change_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    target: SourceStatus,
    reason: str,
) -> SourceRow:
    _require_reason(reason)
    source = await get_source(session, source_id, lock=True)
    current = SourceStatus(source.status)
    if target not in TRANSITIONS[current]:
        raise Conflict(
            f"Cannot change source status from {current.value} to {target.value}",
            code="invalid_status_transition",
            message_fa="این تغییر وضعیت برای منبع مجاز نیست.",
        )
    if target in NEEDS_CLEARANCE:
        clearance = await current_clearance(session, source_id)
        if clearance is None:
            raise Conflict(
                "Source has no access clearance",
                code="clearance_missing",
                message_fa="مجوز دسترسی این منبع ثبت نشده است؛ جمع‌آوری خودکار مجاز نیست.",
            )
        _check_quota(source.quota_per_minute, clearance)
    await _set_status(
        session, tenant_id=tenant_id, actor=actor, source=source, target=target, reason=reason
    )
    return source


async def _set_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source: SourceRow,
    target: SourceStatus,
    reason: str,
) -> None:
    before = source.status
    source.status = target.value
    source.status_reason = reason
    source.updated_at = datetime.now(UTC)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=SourceStatusChanged(source_id=source.id, status=target.value, previous=before),
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.status.changed",
        target_type="source",
        target_id=source.id,
        before={"status": before},
        after={"status": target.value},
        reason=reason,
    )


async def grant_clearance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    approver_name: str,
    approved_on: date,
    scope: str,
    reference: str,
    permitted_requests_per_minute: int,
) -> SourceClearanceRow:
    source = await get_source(session, source_id, lock=True)
    if permitted_requests_per_minute <= 0:
        raise ValidationFailed("Permitted rate must be positive")
    if source.quota_per_minute > permitted_requests_per_minute:
        raise ValidationFailed(
            "Lower the source quota to the permitted rate before recording this clearance",
            code="quota_above_permitted_rate",
            message_fa="ابتدا سقف درخواست منبع را تا نرخ مجاز کاهش دهید.",
        )
    clearance = SourceClearanceRow(
        id=new_id(),
        tenant_id=tenant_id,
        source_id=source_id,
        kind=ClearanceKind.GRANTED.value,
        approver_name=approver_name,
        approved_on=approved_on,
        scope=scope,
        reference=reference,
        permitted_requests_per_minute=permitted_requests_per_minute,
        recorded_by=actor.username,
    )
    session.add(clearance)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.clearance.granted",
        target_type="source",
        target_id=source_id,
        after={
            "approver_name": approver_name,
            "approved_on": approved_on.isoformat(),
            "scope": scope,
            "reference": reference,
            "permitted_requests_per_minute": permitted_requests_per_minute,
        },
    )
    return clearance


async def revoke_clearance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    reason: str,
) -> SourceClearanceRow:
    _require_reason(reason)
    source = await get_source(session, source_id, lock=True)
    if await current_clearance(session, source_id) is None:
        raise Conflict("Source has no clearance to revoke", message_fa="مجوزی برای لغو وجود ندارد.")
    revocation = SourceClearanceRow(
        id=new_id(),
        tenant_id=tenant_id,
        source_id=source_id,
        kind=ClearanceKind.REVOKED.value,
        reason=reason,
        recorded_by=actor.username,
    )
    session.add(revocation)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.clearance.revoked",
        target_type="source",
        target_id=source_id,
        reason=reason,
    )
    if SourceStatus(source.status) in COLLECTABLE:
        await _set_status(
            session,
            tenant_id=tenant_id,
            actor=actor,
            source=source,
            target=SourceStatus.SUSPENDED,
            reason=f"clearance revoked: {reason}",
        )
    return revocation
