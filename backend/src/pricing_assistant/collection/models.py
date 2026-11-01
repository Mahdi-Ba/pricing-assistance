"""Collection persistence: append-only observations and fetch attempts, fetch-window claims and
on-demand re-check requests."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class Validity(StrEnum):
    VALID = "valid"
    SUSPECT_UNIT = "suspect_unit"


class FetchTrigger(StrEnum):
    SCHEDULED = "scheduled"
    RECHECK = "recheck"
    QUALIFICATION = "qualification"


class FetchOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class RecheckStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ObservationRow(Base):
    """One seller offer seen on one successful fetch. Never updated or deleted by the app."""

    __tablename__ = "observation"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracked_offer.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    fetch_attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fetch_attempt.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    url: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    seller: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    price_rial: Mapped[int | None] = mapped_column(BigInteger)
    stock_state: Mapped[str] = mapped_column(Text)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validity: Mapped[str] = mapped_column(Text)
    is_own_store: Mapped[bool] = mapped_column(Boolean)
    is_own_channel: Mapped[bool] = mapped_column(Boolean)
    extraction_rule_version_id: Mapped[uuid.UUID | None]
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FetchAttemptRow(Base):
    __tablename__ = "fetch_attempt"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracked_offer.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    offers_count: Mapped[int] = mapped_column(Integer, server_default="0")
    final: Mapped[bool] = mapped_column(Boolean)
    correlation_id: Mapped[str] = mapped_column(Text)
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FetchClaimRow(Base):
    """Makes a scheduling window execute once, however often it is enqueued."""

    __tablename__ = "fetch_claim"

    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracked_offer.id"), primary_key=True
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    trigger: Mapped[str] = mapped_column(Text)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecheckRequestRow(Base):
    __tablename__ = "recheck_request"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracked_offer.id"))
    requested_by: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    fetch_attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fetch_attempt.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
