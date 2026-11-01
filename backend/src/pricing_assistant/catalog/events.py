"""Domain events published by the `catalog` module."""

import uuid
from typing import ClassVar

from pricing_assistant.core.events import DomainEvent


class CostChanged(DomainEvent):
    """The effective cost in force changed for these variants."""

    event_type: ClassVar[str] = "catalog.cost.changed"
    variant_ids: list[uuid.UUID]
    reason: str


class VariantsChanged(DomainEvent):
    """Catalog data other than cost (e.g. our current price, stock, tier) changed."""

    event_type: ClassVar[str] = "catalog.variants.changed"
    variant_ids: list[uuid.UUID]


class RuleVersionCreated(DomainEvent):
    event_type: ClassVar[str] = "rule.version.created"
    rule_version_id: uuid.UUID
    scope: str
    scope_key: str | None
