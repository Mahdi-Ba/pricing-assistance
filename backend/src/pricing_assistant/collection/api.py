"""Public interface of the `collection` module.

Other modules may import only this file and `events.py`.
"""

from pricing_assistant.collection.evidence import EvidenceStore, presigned_url
from pricing_assistant.collection.freshness import (
    STALE_OR_FAILED_FA,
    Freshness,
    OfferFreshness,
    classify,
    is_fresh,
    offer_freshness,
)
from pricing_assistant.collection.health import SourceHealth, source_health
from pricing_assistant.collection.models import (
    FetchAttemptRow,
    ObservationRow,
    Validity,
)
from pricing_assistant.collection.retention import missing_observations

__all__ = [
    "STALE_OR_FAILED_FA",
    "EvidenceStore",
    "FetchAttemptRow",
    "Freshness",
    "ObservationRow",
    "OfferFreshness",
    "SourceHealth",
    "Validity",
    "classify",
    "is_fresh",
    "missing_observations",
    "offer_freshness",
    "presigned_url",
    "source_health",
]
