"""Public interface of the `sources` module.

Other modules may import only this file and `events.py`.
"""

from pricing_assistant.sources.config import get_config as connector_config
from pricing_assistant.sources.connector import (
    Evidence,
    ExtractionRule,
    FetchContext,
    FetchErrorClass,
    FetchFailure,
    FetchResult,
    ObservationDraft,
    ObservedOffer,
    OfferConditions,
    OfferTarget,
    SourceConnector,
    StockState,
)
from pricing_assistant.sources.connectors.registry import ConnectorRegistry
from pricing_assistant.sources.models import (
    RetrievalMethod,
    SourceRow,
    SourceStatus,
    TrackedOfferRow,
    TrackedOfferStatus,
)
from pricing_assistant.sources.ratelimit import Admission, RecheckBudget, SourceRateLimiter
from pricing_assistant.sources.registry import (
    current_clearance,
    feeds_recommendations,
    get_source,
    may_fetch,
)
from pricing_assistant.sources.runtime import PreparedFetch, prepare_fetch, run_fetch

__all__ = [
    "Admission",
    "ConnectorRegistry",
    "Evidence",
    "ExtractionRule",
    "FetchContext",
    "FetchErrorClass",
    "FetchFailure",
    "FetchResult",
    "ObservationDraft",
    "ObservedOffer",
    "OfferConditions",
    "OfferTarget",
    "PreparedFetch",
    "RecheckBudget",
    "RetrievalMethod",
    "SourceConnector",
    "SourceRateLimiter",
    "SourceRow",
    "SourceStatus",
    "StockState",
    "TrackedOfferRow",
    "TrackedOfferStatus",
    "connector_config",
    "current_clearance",
    "feeds_recommendations",
    "get_source",
    "may_fetch",
    "prepare_fetch",
    "run_fetch",
]
