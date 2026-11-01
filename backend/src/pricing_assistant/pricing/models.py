"""Pricing persistence: append-only recommendations and expert outlier confirmations."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class RecommendationRow(Base):
    __tablename__ = "recommendation"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    outcome: Mapped[str] = mapped_column(Text)
    reason_code: Mapped[str] = mapped_column(Text)
    flags: Mapped[list[str]] = mapped_column(JSONB)
    suggested_price_rial: Mapped[int | None] = mapped_column(BigInteger)
    our_price_rial: Mapped[int | None] = mapped_column(BigInteger)
    floor_rial: Mapped[int | None] = mapped_column(BigInteger)
    ceiling_rial: Mapped[int | None] = mapped_column(BigInteger)
    market_ref_rial: Mapped[int | None] = mapped_column(BigInteger)
    market_ref_observation_id: Mapped[uuid.UUID | None]
    median_rial: Mapped[int | None] = mapped_column(BigInteger)
    qualifying_count: Mapped[int] = mapped_column(Integer)
    qualifying_observation_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    excluded_outlier_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    effective_cost_rial: Mapped[int | None] = mapped_column(BigInteger)
    profit_current_rial: Mapped[int | None] = mapped_column(BigInteger)
    profit_suggested_rial: Mapped[int | None] = mapped_column(BigInteger)
    explanation: Mapped[str] = mapped_column(Text)
    explanation_llm: Mapped[str | None] = mapped_column(Text)  # validated rewording, optional
    observation_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    match_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    outlier_confirmation_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    cost_record_id: Mapped[uuid.UUID | None]
    cost_component_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    rule_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    engine_version: Mapped[str] = mapped_column(Text)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recommendation.id", deferrable=True, initially="DEFERRED")
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutlierConfirmationRow(Base):
    __tablename__ = "outlier_confirmation"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    observation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("observation.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    actor: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
