"""The connector contract every source implements (design D5, task 4.3).

A connector turns one tracked offer into either an :class:`ObservationDraft` (a successful fetch,
possibly listing several sellers' offers on one page) or a :class:`FetchFailure`. A failure never
becomes an observation, and out-of-stock is reported only from an explicit signal on a
successful fetch. Connectors read prices only through official APIs, structured page data or
the source's active extraction rule — never through a language model.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.models import RetrievalMethod


class StockState(StrEnum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class FetchErrorClass(StrEnum):
    NETWORK = "network"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"  # 5xx: transient
    CLIENT_ERROR = "client_error"  # other 4xx: not retried
    NOT_FOUND = "not_found"
    OFF_DOMAIN = "off_domain"  # redirect or URL outside the cleared domain
    BLOCKED = "blocked"
    PARSE_FAILURE = "parse_failure"
    UNEXPECTED_STRUCTURE = "unexpected_structure"
    CLEARANCE_MISSING = "clearance_missing"
    QUOTA_EXHAUSTED = "quota_exhausted"
    CONFIGURATION = "configuration"


RETRYABLE = frozenset(
    {FetchErrorClass.NETWORK, FetchErrorClass.TIMEOUT, FetchErrorClass.HTTP_ERROR}
)


@dataclass(frozen=True, slots=True)
class OfferTarget:
    tracked_offer_id: uuid.UUID
    source_id: uuid.UUID
    variant_id: uuid.UUID
    url: str
    external_id: str | None
    currency_unit: CurrencyUnit
    base_domain: str
    is_own_store: bool = False
    is_own_channel: bool = False


@dataclass(frozen=True, slots=True)
class ExtractionRule:
    """The source's active, admin-approved selector configuration."""

    version_id: uuid.UUID
    config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FetchContext:
    tenant_id: uuid.UUID
    correlation_id: str
    user_agent: str
    timeout_seconds: float
    extraction_rule: ExtractionRule | None = None
    connector_config: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:  # never print secret values
        return (
            f"FetchContext(tenant_id={self.tenant_id}, correlation_id={self.correlation_id!r}, "
            f"secrets={sorted(self.secrets)})"
        )


@dataclass(frozen=True, slots=True)
class OfferConditions:
    """Raw sale conditions as stated by the source, before normalisation."""

    warranty: str | None = None
    condition: str | None = None  # e.g. new, used, open-box, as written on the page
    payment: str | None = None  # e.g. cash, instalment


@dataclass(frozen=True, slots=True)
class ObservedOffer:
    price_rial: int | None
    stock: StockState
    seller: str | None = None
    title: str | None = None
    conditions: OfferConditions = field(default_factory=OfferConditions)
    identifiers: dict[str, str] = field(default_factory=dict)  # mpn, gtin, sku from the page


@dataclass(frozen=True, slots=True)
class Evidence:
    """Raw material kept as proof of what the page showed."""

    html: bytes | None = None
    extracted: dict[str, Any] | None = None
    screenshot_png: bytes | None = None


@dataclass(frozen=True, slots=True)
class ObservationDraft:
    target: OfferTarget
    observed_at: datetime
    method: RetrievalMethod
    offers: list[ObservedOffer]
    evidence: Evidence
    extraction_rule_version_id: uuid.UUID | None = None
    http_status: int | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class FetchFailure:
    error_class: FetchErrorClass
    detail: str
    http_status: int | None = None
    retry_after_seconds: int | None = None
    latency_ms: int | None = None

    @property
    def retryable(self) -> bool:
        return self.error_class in RETRYABLE


FetchResult = ObservationDraft | FetchFailure


@runtime_checkable
class SourceConnector(Protocol):
    """Implemented once per source type; registered under a ``connector_key``."""

    key: str
    method: RetrievalMethod

    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult: ...
