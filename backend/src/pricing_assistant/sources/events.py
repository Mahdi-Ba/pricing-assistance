"""Domain events published by the `sources` module."""

import uuid
from typing import ClassVar

from pricing_assistant.core.events import DomainEvent


class SourceStatusChanged(DomainEvent):
    """A source entered or left the set that may be fetched or may feed recommendations."""

    event_type: ClassVar[str] = "source.status.changed"
    source_id: uuid.UUID
    status: str
    previous: str


class TrackedOfferActivated(DomainEvent):
    event_type: ClassVar[str] = "source.offer.activated"
    tracked_offer_id: uuid.UUID
    variant_id: uuid.UUID


class ExtractionRuleActivated(DomainEvent):
    event_type: ClassVar[str] = "source.extraction_rule.activated"
    source_id: uuid.UUID
    rule_version_id: uuid.UUID


class OfferUrlSuggestionRequested(DomainEvent):
    """An expert asked for LLM offer-URL suggestions; handled by a ``collect`` worker."""

    event_type: ClassVar[str] = "source.offer_urls.requested"
    source_id: uuid.UUID
    variant_id: uuid.UUID
    requested_by: str
