"""Decision persistence. All three tables are append-only (the app role has INSERT and SELECT).

- ``decision``: what the expert decided for one recommendation version. A correction is a new row
  with ``supersedes_decision_id``; the original stays.
- ``override_review``: the admin's verdict on a below-floor override (``approved``/``rejected``),
  or ``self_approved`` when an admin recorded it. At most one per decision.
- ``decision_outcome``: one row per reached stage. The current state is derived from these rows,
  never stored on the decision.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class DecisionType(StrEnum):
    ACCEPT = "accept"
    ACCEPT_MODIFIED = "accept_modified"
    REJECT = "reject"
    DEFER = "defer"


ACCEPT_TYPES = frozenset({DecisionType.ACCEPT, DecisionType.ACCEPT_MODIFIED})


class Verdict(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    SELF_APPROVED = "self_approved"


class Stage(StrEnum):
    REPORTED_DONE = "reported_done"
    OBSERVED_ON_SITE = "observed_on_site"
    REFLECTED_IN_CHANNEL = "reflected_in_channel"
    VERIFICATION_OVERDUE = "verification_overdue"


class DecisionRow(Base):
    __tablename__ = "decision"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    variant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("variant.id"))
    recommendation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation.id"))
    type: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    applied_price_rial: Mapped[int | None] = mapped_column(BigInteger)
    floor_rial: Mapped[int | None] = mapped_column(BigInteger)
    below_floor_override: Mapped[bool] = mapped_column(Boolean)
    override_reason: Mapped[str | None] = mapped_column(Text)
    supersedes_decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decision.id"))
    actor_subject: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OverrideReviewRow(Base):
    __tablename__ = "override_review"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision.id"))
    verdict: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    actor_subject: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DecisionOutcomeRow(Base):
    __tablename__ = "decision_outcome"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("decision.id"))
    stage: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str | None] = mapped_column(Text)
    observation_id: Mapped[uuid.UUID | None]
    delay_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
