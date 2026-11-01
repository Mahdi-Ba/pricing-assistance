"""Domain events published by the `pricing` module."""

import uuid
from typing import ClassVar

from pricing_assistant.core.events import DomainEvent


class RecommendationCreated(DomainEvent):
    event_type: ClassVar[str] = "recommendation.created"
    recommendation_id: uuid.UUID
    variant_id: uuid.UUID
    outcome: str
    superseded_id: uuid.UUID | None


class OutlierConfirmed(DomainEvent):
    event_type: ClassVar[str] = "outlier.confirmed"
    observation_id: uuid.UUID
    variant_id: uuid.UUID
