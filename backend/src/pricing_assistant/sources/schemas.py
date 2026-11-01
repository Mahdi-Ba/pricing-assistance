"""API schemas for the sources module."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.models import RetrievalMethod, SourceStatus

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Domain = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9.-]{3,253}$", to_lower=True)
]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class SourceSettingsIn(ApiModel):
    quota_per_minute: Annotated[int, Field(gt=0, le=600)]
    interval_a_seconds: Annotated[int, Field(ge=60)] = 900
    interval_b_seconds: Annotated[int, Field(ge=60)] = 3600
    interval_c_seconds: Annotated[int, Field(ge=60)] = 21600


class SourceIn(SourceSettingsIn):
    name: Text200
    base_domain: Domain
    connector_key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
    method: RetrievalMethod
    currency_unit: CurrencyUnit


class SourceUpdateIn(ApiModel):
    """Partial edit; omitted fields stay unchanged. Quota and intervals are set together."""

    name: Text200 | None = None
    base_domain: Domain | None = None
    connector_key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")] | None = (
        None
    )
    method: RetrievalMethod | None = None
    currency_unit: CurrencyUnit | None = None
    settings: SourceSettingsIn | None = None


class SourceDeleteIn(ApiModel):
    reason: Reason


class StatusChangeIn(ApiModel):
    status: SourceStatus
    reason: Reason


class ClearanceIn(ApiModel):
    approver_name: Text200
    approved_on: date
    scope: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]
    reference: Text200
    permitted_requests_per_minute: Annotated[int, Field(gt=0, le=600)]


class RevokeIn(ApiModel):
    reason: Reason


class ClearanceOut(ApiModel):
    id: uuid.UUID
    kind: Literal["granted", "revoked"]
    approver_name: str | None
    approved_on: date | None
    scope: str | None
    reference: str | None
    permitted_requests_per_minute: int | None
    reason: str | None
    recorded_by: str
    created_at: datetime


class SourceOut(ApiModel):
    id: uuid.UUID
    name: str
    base_domain: str
    connector_key: str
    method: RetrievalMethod
    currency_unit: CurrencyUnit
    quota_per_minute: int
    interval_a_seconds: int
    interval_b_seconds: int
    interval_c_seconds: int
    status: SourceStatus
    status_reason: str | None
    created_at: datetime
    updated_at: datetime


class SourceDetailOut(SourceOut):
    clearance: ClearanceOut | None
    connector_config: dict[str, Any]
    secrets: dict[str, Literal["set"]]


class ConnectorConfigIn(ApiModel):
    config: dict[str, Any]


class SecretIn(ApiModel):
    value: Annotated[str, StringConstraints(min_length=1, max_length=4096)]


class TrackedOfferIn(ApiModel):
    source_id: uuid.UUID
    variant_id: uuid.UUID
    url: HttpUrl
    external_id: Annotated[str, StringConstraints(max_length=200)] | None = None
    is_own_store: bool = False
    is_own_channel: bool = False


class SuggestionReviewIn(ApiModel):
    decision: Literal["confirm", "dismiss"]
    reason: Reason | None = None


class UrlSuggestionIn(ApiModel):
    variant_id: uuid.UUID


class UrlSuggestionAccepted(ApiModel):
    request_id: uuid.UUID


class PauseIn(ApiModel):
    paused: bool
    reason: Reason


class TrackedOfferOut(ApiModel):
    id: uuid.UUID
    source_id: uuid.UUID
    variant_id: uuid.UUID
    url: str
    external_id: str | None
    status: Literal["suggested", "active", "dismissed", "paused"]
    is_own_store: bool
    is_own_channel: bool
    next_due_at: datetime | None
    suggested_by: str | None
    suggestion_rationale: str | None
    created_by: str
    created_at: datetime
    confirmed_by: str | None
    confirmed_at: datetime | None


class ExtractionRuleIn(ApiModel):
    config: dict[str, Any]


class RuleReviewIn(ApiModel):
    decision: Literal["approve", "reject"]
    reason: Reason


class ExtractionRuleOut(ApiModel):
    id: uuid.UUID
    source_id: uuid.UUID
    version: int
    config: dict[str, Any]
    state: Literal["proposed", "active", "retired", "rejected"]
    origin: Literal["admin", "llm"]
    validation: dict[str, Any] | None
    created_by: str
    created_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_reason: str | None


class SampleOut(ApiModel):
    id: uuid.UUID
    source_id: uuid.UUID
    url: str
    created_by: str
    created_at: datetime


class QualificationRunIn(ApiModel):
    source_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=10)]
    variant_ids: Annotated[list[uuid.UUID], Field(max_length=200)] | None = None
    sample_size: Annotated[int, Field(ge=1, le=200)] = 20


class QualificationDecisionIn(ApiModel):
    decision: Literal["approve", "reject"]
    reason: Reason


class QualificationRunOut(ApiModel):
    id: uuid.UUID
    status: Literal["running", "completed"]
    variant_ids: list[uuid.UUID]
    source_ids: list[uuid.UUID]
    requested_offers: int
    report: dict[str, Any] | None
    started_by: str
    started_at: datetime
    completed_at: datetime | None
