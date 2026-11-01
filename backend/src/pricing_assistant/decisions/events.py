"""Domain events published by the `decisions` module."""

import uuid
from typing import ClassVar

from pricing_assistant.core.events import DomainEvent


class DecisionRecorded(DomainEvent):
    event_type: ClassVar[str] = "decision.recorded"
    decision_id: uuid.UUID
    variant_id: uuid.UUID
    recommendation_id: uuid.UUID
    type: str
    below_floor_override: bool
    supersedes_decision_id: uuid.UUID | None


class OverrideReviewed(DomainEvent):
    event_type: ClassVar[str] = "decision.override.reviewed"
    decision_id: uuid.UUID
    variant_id: uuid.UUID
    verdict: str


class OutcomeReached(DomainEvent):
    event_type: ClassVar[str] = "decision.outcome.reached"
    decision_id: uuid.UUID
    variant_id: uuid.UUID
    stage: str
