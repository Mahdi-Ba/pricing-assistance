"""Public interface of the `catalog` module.

Other modules may import only this file and `events.py`.
"""

from pricing_assistant.catalog.costs import EffectiveCost, effective_cost, effective_cost_from_refs
from pricing_assistant.catalog.models import ImportanceTier
from pricing_assistant.catalog.queries import (
    VariantInfo,
    get_variant,
    list_variants,
    variant_exists,
)
from pricing_assistant.catalog.rules import (
    ResolvedRule,
    resolve_for_variant,
    resolve_for_variants,
    resolve_versions,
)

__all__ = [
    "EffectiveCost",
    "ImportanceTier",
    "ResolvedRule",
    "VariantInfo",
    "effective_cost",
    "effective_cost_from_refs",
    "get_variant",
    "list_variants",
    "resolve_for_variant",
    "resolve_for_variants",
    "resolve_versions",
    "variant_exists",
]
