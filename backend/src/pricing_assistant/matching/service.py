"""Matching workflow (tasks 7.5–7.8).

``observation.recorded`` → :func:`record_attributes` (normalize, version on change) →
``offer.attributes.updated`` → :func:`evaluate` (score against the offer's variant, assign a
state, version on change) → ``match.changed``.

Experts confirm, reject or re-assign through :func:`decide`; every decision is a new version and
an audited event. Automated evaluation never overrides an expert decision while the offer's
attributes are unchanged, and never re-proposes a rejected pair with unchanged attributes.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import SYSTEM_ACTOR, AuditActor, record
from pricing_assistant.catalog.api import VariantInfo, get_variant, list_variants
from pricing_assistant.collection.api import ObservationRow
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.llm.api import LLMPort
from pricing_assistant.matching import assist
from pricing_assistant.matching.events import MatchChanged, OfferAttributesUpdated
from pricing_assistant.matching.extract import (
    Attributes,
    attributes_hash,
    extract,
    from_json,
    seller_key,
    to_json,
)
from pricing_assistant.matching.models import (
    DecisionSource,
    MatchState,
    MatchVersionRow,
    OfferAttributesRow,
    RejectedPairRow,
)
from pricing_assistant.matching.scoring import (
    Assessment,
    VariantProfile,
    assess,
    profile_from_catalog,
)
from pricing_assistant.sources.api import TrackedOfferRow


class ExpertAction(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"
    REASSIGN = "reassign"


@dataclass(frozen=True, slots=True)
class MarketOffer:
    tracked_offer_id: uuid.UUID
    seller_key: str


def profile(info: VariantInfo) -> VariantProfile:
    return profile_from_catalog(
        info.id,
        brand=info.brand,
        model=info.model,
        mpn=info.mpn,
        gtin=info.gtin,
        attributes=info.attributes,
    )


async def latest_attributes(session: AsyncSession, offer: MarketOffer) -> OfferAttributesRow | None:
    row: OfferAttributesRow | None = await session.scalar(
        select(OfferAttributesRow)
        .where(
            OfferAttributesRow.tracked_offer_id == offer.tracked_offer_id,
            OfferAttributesRow.seller_key == offer.seller_key,
        )
        .order_by(OfferAttributesRow.version.desc())
        .limit(1)
    )
    return row


async def current_match(session: AsyncSession, offer: MarketOffer) -> MatchVersionRow | None:
    row: MatchVersionRow | None = await session.scalar(
        select(MatchVersionRow).where(
            MatchVersionRow.tracked_offer_id == offer.tracked_offer_id,
            MatchVersionRow.seller_key == offer.seller_key,
            MatchVersionRow.is_current.is_(True),
        )
    )
    return row


async def record_attributes(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    observation: ObservationRow,
    llm: LLMPort | None = None,
) -> OfferAttributesRow | None:
    """Store a new attribute version if the normalized attributes changed."""
    known_models = [v.model for v in await list_variants(session)]
    attrs = extract(
        observation.title,
        conditions=observation.conditions,
        identifiers=observation.identifiers,
        known_models=known_models,
    )
    offer = MarketOffer(observation.tracked_offer_id, seller_key(observation.seller))
    latest = await latest_attributes(session, offer)
    if llm is not None:
        attrs = await assist.fill_attributes(
            llm,
            tenant_id,
            title=observation.title,
            attrs=attrs,
            latest=latest,
            known_models=known_models,
        )
    digest = attributes_hash(attrs)
    if latest is not None and latest.attributes_hash == digest:
        return None
    row = OfferAttributesRow(
        id=new_id(),
        tenant_id=tenant_id,
        tracked_offer_id=offer.tracked_offer_id,
        seller_key=offer.seller_key,
        version=(latest.version + 1) if latest else 1,
        attributes=to_json(attrs),
        attributes_hash=digest,
        observation_id=observation.id,
    )
    session.add(row)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=OfferAttributesUpdated(
            tracked_offer_id=offer.tracked_offer_id,
            seller_key=offer.seller_key,
            attributes_id=row.id,
        ),
    )
    return row


async def _is_rejected(
    session: AsyncSession, offer: MarketOffer, variant_id: uuid.UUID, digest: str
) -> bool:
    found = await session.scalar(
        select(RejectedPairRow.match_version_id).where(
            RejectedPairRow.tracked_offer_id == offer.tracked_offer_id,
            RejectedPairRow.seller_key == offer.seller_key,
            RejectedPairRow.variant_id == variant_id,
            RejectedPairRow.attributes_hash == digest,
        )
    )
    return found is not None


async def _new_version(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    offer: MarketOffer,
    variant_id: uuid.UUID,
    state: MatchState,
    flags: list[str],
    confidence_bp: int,
    decided_by: DecisionSource,
    actor: str,
    reason: str | None,
    attributes: OfferAttributesRow | None,
    previous: MatchVersionRow | None,
) -> MatchVersionRow:
    if previous is not None:
        previous.is_current = False
        await session.flush()
    version = MatchVersionRow(
        id=new_id(),
        tenant_id=tenant_id,
        tracked_offer_id=offer.tracked_offer_id,
        seller_key=offer.seller_key,
        variant_id=variant_id,
        state=state.value,
        flags=flags,
        confidence_bp=confidence_bp,
        decided_by=decided_by.value,
        actor=actor,
        reason=reason,
        attributes_id=attributes.id if attributes else None,
        attributes_hash=attributes.attributes_hash
        if attributes
        else (previous.attributes_hash if previous else ""),
        previous_version_id=previous.id if previous else None,
        is_current=True,
    )
    session.add(version)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=MatchChanged(
            tracked_offer_id=offer.tracked_offer_id,
            seller_key=offer.seller_key,
            match_version_id=version.id,
            variant_id=variant_id,
            previous_variant_id=previous.variant_id if previous else None,
            state=state.value,
        ),
    )
    return version


def _same(current: MatchVersionRow, result: Assessment) -> bool:
    return (
        current.variant_id == result.variant_id
        and current.state == result.state.value
        and sorted(current.flags) == sorted(result.flags)
    )


async def evaluate(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    offer: MarketOffer,
    *,
    proposed_by: DecisionSource = DecisionSource.RULE,
    attributes_override: Attributes | None = None,
    llm: LLMPort | None = None,
) -> MatchVersionRow | None:
    """Assess the offer against its tracked variant; write a version if the outcome changed.

    With an enabled LLM port, an offer held back only for missing attributes may get an LLM
    match proposal (``proposed``, never ``confirmed``).
    """
    tracked = await session.get(TrackedOfferRow, offer.tracked_offer_id)
    if tracked is None or tracked.is_own_store or tracked.is_own_channel:
        return None
    attributes = await latest_attributes(session, offer)
    if attributes is None:
        return None
    current = await current_match(session, offer)
    variant_id = current.variant_id if current is not None else tracked.variant_id
    if (
        current is not None
        and current.decided_by in (DecisionSource.HUMAN.value, DecisionSource.LLM.value)
        and current.attributes_hash == attributes.attributes_hash
    ):
        return None  # an expert decided (or the model proposed) on exactly these attributes
    if await _is_rejected(session, offer, variant_id, attributes.attributes_hash):
        return None
    info = await get_variant(session, variant_id)
    if info is None:
        return None
    attrs = attributes_override or from_json(attributes.attributes)
    result = assess(attrs, profile(info), proposed_by=proposed_by)
    if (
        current is not None
        and _same(current, result)
        and current.attributes_hash == attributes.attributes_hash
    ):
        return None
    reason = None
    if llm is not None:
        result, reason = await assist.propose(
            session,
            llm,
            tenant_id,
            attributes=attributes,
            attrs=attrs,
            variant=info,
            result=result,
        )
    version = await _new_version(
        session,
        tenant_id=tenant_id,
        offer=offer,
        variant_id=result.variant_id,
        state=result.state,
        flags=result.flags,
        confidence_bp=result.confidence_bp,
        decided_by=result.decided_by,
        actor=SYSTEM_ACTOR.username,
        reason=reason,
        attributes=attributes,
        previous=current,
    )
    if result.is_auto_confirmed:
        await record(
            session,
            tenant_id=tenant_id,
            actor=SYSTEM_ACTOR,
            action="match.auto_confirmed",
            target_type="match_version",
            target_id=version.id,
            after={
                "tracked_offer_id": str(offer.tracked_offer_id),
                "seller_key": offer.seller_key,
                "variant_id": str(variant_id),
                "rule": "exact_identifier",
            },
        )
    return version


async def decide(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    match_version_id: uuid.UUID,
    action: ExpertAction,
    reason: str | None,
    target_variant_id: uuid.UUID | None = None,
) -> MatchVersionRow:
    current = await session.get(MatchVersionRow, match_version_id, with_for_update=True)
    if current is None:
        raise NotFound("Match not found", message_fa="تطبیق یافت نشد.")
    if not current.is_current:
        raise Conflict(
            "This match version was superseded",
            code="match_superseded",
            message_fa="این تطبیق تغییر کرده است؛ نسخه جدید را بررسی کنید.",
        )
    reason = (reason or "").strip() or None
    needs_reason = action in {ExpertAction.REJECT, ExpertAction.REASSIGN} or any(
        flag.startswith("condition_mismatch") for flag in current.flags
    )
    if needs_reason and reason is None:
        raise ValidationFailed(
            "A reason is required for this decision",
            code="reason_required",
            message_fa="برای این تصمیم، دلیل را وارد کنید.",
        )
    offer = MarketOffer(current.tracked_offer_id, current.seller_key)
    attributes = await latest_attributes(session, offer)
    variant_id = current.variant_id
    state = MatchState.CONFIRMED
    if action is ExpertAction.REJECT:
        state = MatchState.REJECTED
    elif action is ExpertAction.REASSIGN:
        if target_variant_id is None or await get_variant(session, target_variant_id) is None:
            raise ValidationFailed(
                "A valid target variant is required", message_fa="کالای مقصد معتبر نیست."
            )
        if target_variant_id == current.variant_id:
            raise ValidationFailed(
                "Re-assign to a different variant", message_fa="کالای دیگری را انتخاب کنید."
            )
        variant_id = target_variant_id
    version = await _new_version(
        session,
        tenant_id=tenant_id,
        offer=offer,
        variant_id=variant_id,
        state=state,
        flags=[f for f in current.flags if action is not ExpertAction.REASSIGN],
        confidence_bp=10_000 if state is MatchState.CONFIRMED else 0,
        decided_by=DecisionSource.HUMAN,
        actor=actor.username,
        reason=reason,
        attributes=attributes,
        previous=current,
    )
    if action is ExpertAction.REJECT:
        session.add(
            RejectedPairRow(
                tracked_offer_id=offer.tracked_offer_id,
                seller_key=offer.seller_key,
                variant_id=current.variant_id,
                attributes_hash=version.attributes_hash,
                tenant_id=tenant_id,
                match_version_id=version.id,
            )
        )
        await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=f"match.{action.value}",
        target_type="match_version",
        target_id=version.id,
        before={
            "state": current.state,
            "variant_id": str(current.variant_id),
            "flags": current.flags,
        },
        after={"state": version.state, "variant_id": str(version.variant_id)},
        reason=reason,
    )
    return version


async def history(session: AsyncSession, offer: MarketOffer) -> list[MatchVersionRow]:
    rows = await session.scalars(
        select(MatchVersionRow)
        .where(
            MatchVersionRow.tracked_offer_id == offer.tracked_offer_id,
            MatchVersionRow.seller_key == offer.seller_key,
        )
        .order_by(MatchVersionRow.created_at, MatchVersionRow.id)
    )
    return list(rows.all())
