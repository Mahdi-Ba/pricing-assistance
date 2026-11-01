"""Source registry persistence: sources, access clearances, connector configuration and secrets,
versioned extraction rules and tracked offers."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class RetrievalMethod(StrEnum):
    API = "api"
    HTML = "html"
    RENDERED_PAGE = "rendered_page"


class SourceStatus(StrEnum):
    CANDIDATE = "candidate"
    UNDER_EVALUATION = "under_evaluation"
    APPROVED = "approved"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class ClearanceKind(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class RuleVersionState(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    RETIRED = "retired"
    REJECTED = "rejected"


class RuleOrigin(StrEnum):
    ADMIN = "admin"
    LLM = "llm"


class TrackedOfferStatus(StrEnum):
    SUGGESTED = "suggested"
    ACTIVE = "active"
    DISMISSED = "dismissed"
    PAUSED = "paused"


class SourceRow(Base):
    __tablename__ = "source"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    name: Mapped[str] = mapped_column(Text)
    base_domain: Mapped[str] = mapped_column(Text)
    connector_key: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    currency_unit: Mapped[str] = mapped_column(Text)
    quota_per_minute: Mapped[int] = mapped_column(Integer)
    interval_a_seconds: Mapped[int] = mapped_column(Integer)
    interval_b_seconds: Mapped[int] = mapped_column(Integer)
    interval_c_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default=SourceStatus.CANDIDATE.value)
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceClearanceRow(Base):
    """Append-only record of who cleared automated access to a source, or revoked it."""

    __tablename__ = "source_clearance"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    kind: Mapped[str] = mapped_column(Text)
    approver_name: Mapped[str | None] = mapped_column(Text)
    approved_on: Mapped[date | None] = mapped_column(Date)
    scope: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    permitted_requests_per_minute: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConnectorConfigRow(Base):
    """Non-secret connector settings. Secret values live in ``connector_secret``, encrypted."""

    __tablename__ = "connector_config"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConnectorSecretRow(Base):
    __tablename__ = "connector_secret"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"), primary_key=True)
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtractionRuleVersionRow(Base):
    __tablename__ = "extraction_rule_version"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)


class TrackedOfferRow(Base):
    __tablename__ = "tracked_offer"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    url: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    is_own_store: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_own_channel: Mapped[bool] = mapped_column(Boolean, server_default="false")
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suggested_by: Mapped[str | None] = mapped_column(Text)
    suggestion_rationale: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_by: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
