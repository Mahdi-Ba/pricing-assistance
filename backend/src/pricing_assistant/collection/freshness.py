"""Freshness of tracked offers (task 5.5).

An offer's newest valid observation is ``stale`` once its age exceeds the maximum data age for
the variant's importance tier in the applicable profit rule. An offer whose latest final fetch
failed after that observation is ``failed``. Both are shown as «قدیمی / دریافت ناموفق» with the
last valid price and its time; neither can support an actionable recommendation.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.collection.metrics import DATA_AGE_SECONDS
from pricing_assistant.collection.models import (
    FetchAttemptRow,
    FetchOutcome,
    ObservationRow,
    Validity,
)

STALE_OR_FAILED_FA = "قدیمی / دریافت ناموفق"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    FAILED = "failed"
    NEVER_OBSERVED = "never_observed"

    @property
    def label_fa(self) -> str | None:
        if self is Freshness.FRESH:
            return None
        if self is Freshness.NEVER_OBSERVED:
            return "هنوز مشاهده نشده"
        return STALE_OR_FAILED_FA


@dataclass(frozen=True, slots=True)
class OfferFreshness:
    tracked_offer_id: uuid.UUID
    state: Freshness
    last_observed_at: datetime | None
    age_seconds: int | None
    last_failure_at: datetime | None


def classify(
    *,
    last_observed_at: datetime | None,
    last_failure_at: datetime | None,
    max_age_seconds: int,
    now: datetime,
) -> Freshness:
    if last_observed_at is None:
        return Freshness.NEVER_OBSERVED
    if last_failure_at is not None and last_failure_at > last_observed_at:
        return Freshness.FAILED
    if (now - last_observed_at).total_seconds() > max_age_seconds:
        return Freshness.STALE
    return Freshness.FRESH


def _pairs(rows: Iterable[tuple[uuid.UUID, datetime]]) -> dict[uuid.UUID, datetime]:
    return {key: value for key, value in rows}


def is_fresh(observed_at: datetime, max_age_seconds: int, now: datetime) -> bool:
    return (now - observed_at).total_seconds() <= max_age_seconds


async def offer_freshness(
    session: AsyncSession,
    tracked_offer_ids: Iterable[uuid.UUID],
    *,
    max_age_seconds: int,
    now: datetime | None = None,
) -> dict[uuid.UUID, OfferFreshness]:
    """Freshness for offers that share one maximum data age (one variant's tier)."""
    ids = list(tracked_offer_ids)
    if not ids:
        return {}
    now = now or datetime.now(UTC)
    observed: dict[uuid.UUID, datetime] = _pairs(
        (
            await session.execute(
                select(ObservationRow.tracked_offer_id, func.max(ObservationRow.observed_at))
                .where(
                    ObservationRow.tracked_offer_id.in_(ids),
                    ObservationRow.validity == Validity.VALID.value,
                )
                .group_by(ObservationRow.tracked_offer_id)
            )
        ).all()
    )
    failed: dict[uuid.UUID, datetime] = _pairs(
        (
            await session.execute(
                select(FetchAttemptRow.tracked_offer_id, func.max(FetchAttemptRow.finished_at))
                .where(
                    FetchAttemptRow.tracked_offer_id.in_(ids),
                    FetchAttemptRow.outcome == FetchOutcome.FAILURE.value,
                    FetchAttemptRow.final.is_(True),
                )
                .group_by(FetchAttemptRow.tracked_offer_id)
            )
        ).all()
    )
    result: dict[uuid.UUID, OfferFreshness] = {}
    for offer_id in ids:
        last = observed.get(offer_id)
        age = int((now - last).total_seconds()) if last else None
        if age is not None:
            DATA_AGE_SECONDS.observe(age)
        result[offer_id] = OfferFreshness(
            tracked_offer_id=offer_id,
            state=classify(
                last_observed_at=last,
                last_failure_at=failed.get(offer_id),
                max_age_seconds=max_age_seconds,
                now=now,
            ),
            last_observed_at=last,
            age_seconds=age,
            last_failure_at=failed.get(offer_id),
        )
    return result
