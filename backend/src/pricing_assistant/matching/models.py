"""Matching persistence.

A *market offer* is one seller's offer on one tracked page: ``(tracked_offer_id, seller_key)``.
Product identity comes from the page; sale conditions (warranty, payment, condition) can differ
per seller, so matches are decided per market offer.

- ``offer_attributes``: versioned normalized attributes, each with its provenance.
- ``match_version``: append-only history of match decisions; exactly one current version per
  market offer (partial unique index). Only ``is_current`` may be updated.
- ``rejected_pair``: offer–variant pairs an expert rejected, keyed by the attribute hash, so the
  same pair is not proposed again unless the offer's attributes change.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class MatchState(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class AttributeSource(StrEnum):
    STRUCTURED_DATA = "structured_data"
    RULE = "rule"
    LLM = "llm"
    HUMAN = "human"


class DecisionSource(StrEnum):
    RULE = "rule"
    LLM = "llm"
    HUMAN = "human"


class OfferAttributesRow(Base):
    __tablename__ = "offer_attributes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracked_offer.id"))
    seller_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attributes_hash: Mapped[str] = mapped_column(Text)
    observation_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchVersionRow(Base):
    __tablename__ = "match_version"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracked_offer.id"))
    seller_key: Mapped[str] = mapped_column(Text)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    state: Mapped[str] = mapped_column(Text)
    flags: Mapped[list[str]] = mapped_column(JSONB)
    confidence_bp: Mapped[int] = mapped_column(Integer)
    decided_by: Mapped[str] = mapped_column(Text)  # rule | llm | human
    actor: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    attributes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offer_attributes.id"))
    attributes_hash: Mapped[str] = mapped_column(Text)
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("match_version.id"))
    is_current: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RejectedPairRow(Base):
    __tablename__ = "rejected_pair"

    tracked_offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracked_offer.id"), primary_key=True
    )
    seller_key: Mapped[str] = mapped_column(Text, primary_key=True)
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"), primary_key=True)
    attributes_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    match_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("match_version.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
