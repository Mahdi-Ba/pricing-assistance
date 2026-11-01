"""Reporting persistence: match audit samples (verdicts recorded once) and review baselines."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class MatchAuditSampleRow(Base):
    __tablename__ = "match_audit_sample"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    period: Mapped[str] = mapped_column(Text)
    population: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(BigInteger)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchAuditItemRow(Base):
    __tablename__ = "match_audit_item"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    sample_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("match_audit_sample.id"))
    match_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("match_version.id"))
    category: Mapped[str] = mapped_column(Text)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    confidence_band: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewBaselineRow(Base):
    __tablename__ = "review_baseline"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    category: Mapped[str] = mapped_column(Text)
    median_seconds: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    entered_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
