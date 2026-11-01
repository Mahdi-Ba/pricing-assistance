"""API schemas for the catalog module. Money is integer Rial; ratios are basis points."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pricing_assistant.catalog.rules import RuleFields

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ImportErrorOut(ApiModel):
    row: int | None
    column: str | None
    message_fa: str


class ImportReportOut(ApiModel):
    id: uuid.UUID
    file_name: str
    status: Literal["succeeded", "partially_succeeded", "failed", "rejected"]
    content_hash: str
    default_currency: str | None
    rows_total: int
    rows_created: int
    rows_updated: int
    rows_unchanged: int
    rows_rejected: int
    rows_held: int
    errors: list[ImportErrorOut]
    uploaded_by: str
    created_at: datetime


class CostComponentIn(ApiModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    amount_rial: Annotated[int, Field(ge=0)]
    category: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_\-]{1,40}$")] | None = None


class CostComponentOut(ApiModel):
    id: uuid.UUID
    name: str
    amount_rial: int
    category: str | None
    active: bool
    created_by: str
    created_at: datetime
    deactivated_by: str | None
    deactivated_at: datetime | None


class ReasonIn(ApiModel):
    reason: Reason


class CostReviewIn(ApiModel):
    decision: Literal["confirm", "reject"]
    reason: Reason


class CostRecordOut(ApiModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    purchase_cost_rial: int
    previous_cost_rial: int | None
    state: Literal["applied", "held", "confirmed", "rejected"]
    import_id: uuid.UUID | None
    uploaded_by: str
    created_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_reason: str | None


class RuleValuesIn(ApiModel):
    """Values a rule version sets; omitted or null fields inherit from the less specific scope."""

    min_margin_bp: Annotated[int, Field(ge=0, le=9_999)] | None = None
    fee_rate_bp: Annotated[int, Field(ge=0, le=9_999)] | None = None
    vat_rate_bp: Annotated[int, Field(ge=0, le=10_000)] | None = None
    ceiling_rial: Annotated[int, Field(gt=0)] | None = None
    undercut_step_rial: Annotated[int, Field(gt=0)] | None = None
    hold_tolerance_bp: Annotated[int, Field(ge=0, le=9_999)] | None = None
    rounding_step_rial: Annotated[int, Field(gt=0)] | None = None
    max_data_age_a_seconds: Annotated[int, Field(gt=0)] | None = None
    max_data_age_b_seconds: Annotated[int, Field(gt=0)] | None = None
    max_data_age_c_seconds: Annotated[int, Field(gt=0)] | None = None
    outlier_threshold_bp: Annotated[int, Field(ge=0, le=9_999)] | None = None
    min_qualifying_offers: Annotated[int, Field(ge=1)] | None = None
    competitor_set: dict[uuid.UUID, list[str]] | None = None

    def to_fields(self) -> RuleFields:
        data = self.model_dump()
        if self.competitor_set is not None:
            data["competitor_set"] = {str(k): v for k, v in self.competitor_set.items()}
        return RuleFields(**data)


class RuleVersionIn(RuleValuesIn):
    reason: Reason | None = None


class RuleVersionOut(ApiModel):
    id: uuid.UUID
    scope: Literal["default", "category", "variant"]
    scope_key: str | None
    version: int
    min_margin_bp: int | None
    fee_rate_bp: int | None
    vat_rate_bp: int | None
    ceiling_rial: int | None
    undercut_step_rial: int | None
    hold_tolerance_bp: int | None
    rounding_step_rial: int | None
    max_data_age_a_seconds: int | None
    max_data_age_b_seconds: int | None
    max_data_age_c_seconds: int | None
    outlier_threshold_bp: int | None
    min_qualifying_offers: int | None
    competitor_set: dict[str, list[str]] | None
    reason: str | None
    created_by: str
    created_at: datetime


class ResolvedRuleOut(ApiModel):
    variant_id: uuid.UUID
    min_margin_bp: int
    fee_rate_bp: int
    vat_rate_bp: int
    ceiling_rial: int | None
    undercut_step_rial: int
    hold_tolerance_bp: int
    rounding_step_rial: int
    max_data_age_seconds: dict[str, int]
    outlier_threshold_bp: int
    min_qualifying_offers: int
    competitor_set: dict[str, list[str]]
    version_ids: list[uuid.UUID]


class VariantSummaryOut(ApiModel):
    """A variant as listed for experts: identity and tier, no cost data."""

    id: uuid.UUID
    sku: str
    product_name: str
    category: str
    brand: str
    model: str
    importance_tier: str
    attributes: dict[str, Any]
