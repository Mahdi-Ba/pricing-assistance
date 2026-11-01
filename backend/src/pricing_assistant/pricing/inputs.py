"""Gathering the engine's inputs for one variant from the other modules (task 9.5)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.api import (
    EffectiveCost,
    ResolvedRule,
    VariantInfo,
    effective_cost,
    get_variant,
    resolve_for_variant,
)
from pricing_assistant.collection.api import ObservationRow, Validity
from pricing_assistant.core.text import normalize_key
from pricing_assistant.matching.api import (
    DecisionSource,
    MatchState,
    MatchVersionRow,
    current_matches_for_variant,
)
from pricing_assistant.pricing.engine import OfferInput, RecommendationInputs
from pricing_assistant.pricing.models import OutlierConfirmationRow
from pricing_assistant.sources.api import SourceRow, TrackedOfferRow, feeds_recommendations

RECENT_OBSERVATIONS = 200


@dataclass(frozen=True, slots=True)
class Gathered:
    variant: VariantInfo
    inputs: RecommendationInputs
    rule: ResolvedRule | None
    cost: EffectiveCost | None
    match_version_ids: tuple[uuid.UUID, ...]
    outlier_confirmation_ids: tuple[uuid.UUID, ...]
    sources: dict[uuid.UUID, str] = field(default_factory=dict)
    sellers: dict[uuid.UUID, str | None] = field(default_factory=dict)


def condition_equivalent(match: MatchVersionRow) -> bool:
    """Equivalent unless a sale condition differs and no expert confirmed equivalence."""
    mismatch = any(flag.startswith("condition_mismatch") for flag in match.flags)
    expert_confirmed = (
        match.decided_by == DecisionSource.HUMAN.value and match.state == MatchState.CONFIRMED.value
    )
    return not mismatch or expert_confirmed


async def _latest_observation(
    session: AsyncSession, match: MatchVersionRow
) -> ObservationRow | None:
    rows = (
        await session.scalars(
            select(ObservationRow)
            .where(ObservationRow.tracked_offer_id == match.tracked_offer_id)
            .order_by(ObservationRow.observed_at.desc())
            .limit(RECENT_OBSERVATIONS)
        )
    ).all()
    return next((o for o in rows if normalize_key(o.seller) == match.seller_key), None)


async def our_current_price(session: AsyncSession, variant: VariantInfo) -> int | None:
    """Newer of the catalog price and the latest valid own-storefront observation."""
    own = await session.scalar(
        select(ObservationRow)
        .join(TrackedOfferRow, TrackedOfferRow.id == ObservationRow.tracked_offer_id)
        .where(
            ObservationRow.variant_id == variant.id,
            ObservationRow.is_own_store.is_(True),
            ObservationRow.validity == Validity.VALID.value,
            ObservationRow.price_rial.is_not(None),
        )
        .order_by(ObservationRow.observed_at.desc())
        .limit(1)
    )
    if own is not None and own.observed_at > variant.updated_at:
        return own.price_rial
    return variant.current_price_rial


async def gather(session: AsyncSession, variant_id: uuid.UUID, now: datetime) -> Gathered | None:
    variant = await get_variant(session, variant_id)
    if variant is None:
        return None
    cost = await effective_cost(session, variant_id)
    rule = await resolve_for_variant(session, variant_id)
    matches = [
        m
        for m in await current_matches_for_variant(session, variant_id)
        if m.state != MatchState.REJECTED.value
    ]
    observations = {m.id: await _latest_observation(session, m) for m in matches}
    observed_ids = [o.id for o in observations.values() if o is not None]
    confirmations = (
        (
            await session.scalars(
                select(OutlierConfirmationRow).where(
                    OutlierConfirmationRow.observation_id.in_(observed_ids)
                )
            )
        ).all()
        if observed_ids
        else []
    )
    confirmed_outliers = {c.observation_id: c.id for c in confirmations}
    source_ids = {o.source_id for o in observations.values() if o is not None}
    sources = (
        {
            s.id: s
            for s in (
                await session.scalars(select(SourceRow).where(SourceRow.id.in_(source_ids)))
            ).all()
        }
        if source_ids
        else {}
    )
    offers: list[OfferInput] = []
    for match in matches:
        observation = observations[match.id]
        if observation is None:
            continue
        source = sources.get(observation.source_id)
        offers.append(
            OfferInput(
                observation_id=observation.id,
                source_id=observation.source_id,
                seller=observation.seller,
                price_rial=observation.price_rial,
                in_stock=observation.stock_state == "in_stock",
                valid=observation.validity == Validity.VALID.value,
                observed_at=observation.observed_at,
                match_version_id=match.id,
                match_confirmed=match.state == MatchState.CONFIRMED.value,
                match_pending=match.state
                in (MatchState.PROPOSED.value, MatchState.NEEDS_REVIEW.value),
                condition_equivalent=condition_equivalent(match),
                source_approved=source is not None and feeds_recommendations(source.status),
                outlier_confirmed=observation.id in confirmed_outliers,
            )
        )
    offers.sort(key=lambda o: str(o.observation_id))
    inputs = RecommendationInputs(
        variant_id=variant_id,
        tier=variant.importance_tier,
        our_price_rial=await our_current_price(session, variant),
        effective_cost_rial=cost.total_rial if cost else None,
        evaluated_at=now,
        offers=tuple(offers),
    )
    return Gathered(
        variant=variant,
        inputs=inputs,
        rule=rule,
        cost=cost,
        match_version_ids=tuple(sorted({o.match_version_id for o in offers}, key=str)),
        outlier_confirmation_ids=tuple(
            sorted(
                (confirmed_outliers[o.observation_id] for o in offers if o.outlier_confirmed),
                key=str,
            )
        ),
        sources={sid: s.name for sid, s in sources.items()},
        sellers={o.observation_id: o.seller for o in offers},
    )
