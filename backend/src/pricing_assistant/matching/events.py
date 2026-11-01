"""Domain events published by the `matching` module."""

import uuid
from typing import ClassVar

from pricing_assistant.core.events import DomainEvent


class OfferAttributesUpdated(DomainEvent):
    event_type: ClassVar[str] = "offer.attributes.updated"
    tracked_offer_id: uuid.UUID
    seller_key: str
    attributes_id: uuid.UUID


class MatchChanged(DomainEvent):
    """The current match of a market offer changed (state, variant or flags)."""

    event_type: ClassVar[str] = "match.changed"
    tracked_offer_id: uuid.UUID
    seller_key: str
    match_version_id: uuid.UUID
    variant_id: uuid.UUID
    previous_variant_id: uuid.UUID | None
    state: str
