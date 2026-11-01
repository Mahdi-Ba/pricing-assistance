"""Domain events published by the `collection` module."""

import uuid
from datetime import datetime
from typing import ClassVar

from pricing_assistant.core.events import DomainEvent


class FetchRequested(DomainEvent):
    """Fetch one tracked offer for one scheduling window (HTTP/API workers)."""

    event_type: ClassVar[str] = "fetch.requested"
    tracked_offer_id: uuid.UUID
    window_start: datetime
    trigger: str
    attempt: int = 1
    deferrals: int = 0
    recheck_id: uuid.UUID | None = None
    slot_reserved: bool = False


class BrowserFetchRequested(FetchRequested):
    """Same request, routed to the browser workers for ``rendered_page`` sources."""

    event_type: ClassVar[str] = "fetch.requested.browser"


class ObservationRecorded(DomainEvent):
    event_type: ClassVar[str] = "observation.recorded"
    observation_ids: list[uuid.UUID]
    tracked_offer_id: uuid.UUID
    variant_id: uuid.UUID
    source_id: uuid.UUID
    is_own_store: bool
    is_own_channel: bool


class FetchFailed(DomainEvent):
    event_type: ClassVar[str] = "fetch.failed"
    tracked_offer_id: uuid.UUID
    variant_id: uuid.UUID
    source_id: uuid.UUID
    error_class: str
    final: bool
