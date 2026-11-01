"""Public interface of the `matching` module.

Other modules may import only this file and `events.py`.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.api import VariantInfo
from pricing_assistant.matching.extract import from_json, seller_key
from pricing_assistant.matching.models import (
    DecisionSource,
    MatchState,
    MatchVersionRow,
    OfferAttributesRow,
)
from pricing_assistant.matching.scoring import AttributeComparison, compare
from pricing_assistant.matching.service import (
    MarketOffer,
    current_match,
    latest_attributes,
    profile,
)


async def current_matches(
    session: AsyncSession, tracked_offer_ids: Iterable[uuid.UUID]
) -> list[MatchVersionRow]:
    ids = list(tracked_offer_ids)
    if not ids:
        return []
    rows = await session.scalars(
        select(MatchVersionRow).where(
            MatchVersionRow.tracked_offer_id.in_(ids), MatchVersionRow.is_current.is_(True)
        )
    )
    return list(rows.all())


async def current_matches_for_variant(
    session: AsyncSession, variant_id: uuid.UUID
) -> list[MatchVersionRow]:
    rows = await session.scalars(
        select(MatchVersionRow).where(
            MatchVersionRow.variant_id == variant_id, MatchVersionRow.is_current.is_(True)
        )
    )
    return list(rows.all())


async def pending_matches(session: AsyncSession) -> list[MatchVersionRow]:
    """Current ``proposed`` and ``needs_review`` matches, oldest first."""
    rows = await session.scalars(
        select(MatchVersionRow)
        .where(
            MatchVersionRow.is_current.is_(True),
            MatchVersionRow.state.in_([MatchState.PROPOSED.value, MatchState.NEEDS_REVIEW.value]),
        )
        .order_by(MatchVersionRow.created_at, MatchVersionRow.id)
    )
    return list(rows.all())


async def side_by_side(
    session: AsyncSession, match: MatchVersionRow, variant: VariantInfo
) -> list[AttributeComparison]:
    attributes = await latest_attributes(
        session, MarketOffer(match.tracked_offer_id, match.seller_key)
    )
    offer = from_json(attributes.attributes) if attributes is not None else {}
    return compare(offer, profile(variant))


__all__ = [
    "AttributeComparison",
    "DecisionSource",
    "MarketOffer",
    "MatchState",
    "MatchVersionRow",
    "OfferAttributesRow",
    "current_match",
    "current_matches",
    "current_matches_for_variant",
    "pending_matches",
    "seller_key",
    "side_by_side",
]
