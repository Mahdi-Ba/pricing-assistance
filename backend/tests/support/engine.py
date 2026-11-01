"""Builders for engine inputs and rules."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from pricing_assistant.catalog.api import ImportanceTier, ResolvedRule
from pricing_assistant.catalog.rules import SUGGESTED_DEFAULTS, RuleFields, resolve
from pricing_assistant.pricing.engine import OfferInput, RecommendationInputs

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
SOURCE = uuid.UUID("00000000-0000-7000-8000-00000000aaaa")


def rule(**overrides: object) -> ResolvedRule:
    """Suggested defaults with VAT 0 and a 1-Rial rounding step unless overridden."""
    fields = SUGGESTED_DEFAULTS.overlay(RuleFields(vat_rate_bp=0, rounding_step_rial=1))
    resolved = resolve([(uuid.uuid4(), fields.overlay(RuleFields(**overrides)))])  # type: ignore[arg-type]
    assert resolved is not None
    return resolved


def offer(price: int | None, **overrides: object) -> OfferInput:
    base = OfferInput(
        observation_id=uuid.uuid4(),
        source_id=SOURCE,
        seller="لیون کامپیوتر",
        price_rial=price,
        in_stock=True,
        valid=True,
        observed_at=NOW - timedelta(minutes=8),
        match_version_id=uuid.uuid4(),
        match_confirmed=True,
        match_pending=False,
        condition_equivalent=True,
        source_approved=True,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def inputs(
    *offers: OfferInput,
    our: int | None = 89_000_000,
    cost: int | None = 75_000_000,
    tier: ImportanceTier = ImportanceTier.A,
) -> RecommendationInputs:
    return RecommendationInputs(
        variant_id=uuid.UUID("00000000-0000-7000-8000-00000000bbbb"),
        tier=tier,
        our_price_rial=our,
        effective_cost_rial=cost,
        evaluated_at=NOW,
        offers=offers,
    )
