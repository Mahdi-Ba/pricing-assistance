"""Match confirmation queue: pending matches side by side, plus suggested offer URLs (11.5)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.api import VariantInfo, list_variants
from pricing_assistant.collection.api import ObservationRow
from pricing_assistant.matching.api import (
    AttributeComparison,
    MatchVersionRow,
    pending_matches,
    seller_key,
    side_by_side,
)
from pricing_assistant.sources.api import SourceRow, TrackedOfferRow, TrackedOfferStatus


@dataclass(frozen=True, slots=True)
class PendingMatch:
    match: MatchVersionRow
    variant: VariantInfo
    offer: TrackedOfferRow
    source_name: str
    observation: ObservationRow | None  # newest observation of this seller on the offer page
    attributes: list[AttributeComparison]


@dataclass(frozen=True, slots=True)
class SuggestedOffer:
    offer: TrackedOfferRow
    variant: VariantInfo
    source_name: str


async def _latest_observation(
    session: AsyncSession, match: MatchVersionRow
) -> ObservationRow | None:
    rows = await session.scalars(
        select(ObservationRow)
        .where(ObservationRow.tracked_offer_id == match.tracked_offer_id)
        .order_by(ObservationRow.observed_at.desc())
        .limit(20)
    )
    return next((o for o in rows.all() if seller_key(o.seller) == match.seller_key), None)


async def match_queue(session: AsyncSession) -> tuple[list[PendingMatch], list[SuggestedOffer]]:
    variants = {v.id: v for v in await list_variants(session)}
    sources = {s.id: s.name for s in (await session.scalars(select(SourceRow))).all()}
    pending: list[PendingMatch] = []
    for match in await pending_matches(session):
        variant = variants.get(match.variant_id)
        offer = await session.get(TrackedOfferRow, match.tracked_offer_id)
        if variant is None or offer is None:
            continue
        pending.append(
            PendingMatch(
                match=match,
                variant=variant,
                offer=offer,
                source_name=sources.get(offer.source_id, ""),
                observation=await _latest_observation(session, match),
                attributes=await side_by_side(session, match, variant),
            )
        )
    suggested = [
        SuggestedOffer(
            offer=o, variant=variants[o.variant_id], source_name=sources.get(o.source_id, "")
        )
        for o in (
            await session.scalars(
                select(TrackedOfferRow)
                .where(TrackedOfferRow.status == TrackedOfferStatus.SUGGESTED.value)
                .order_by(TrackedOfferRow.created_at)
            )
        ).all()
        if o.variant_id in variants
    ]
    return pending, suggested


def pending_count(pending: list[PendingMatch], suggested: list[SuggestedOffer]) -> int:
    """The «pending match confirmations» card: exactly the length of the match queue."""
    return len(pending) + len(suggested)


__all__ = ["PendingMatch", "SuggestedOffer", "match_queue", "pending_count"]
