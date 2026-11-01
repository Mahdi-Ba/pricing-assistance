"""Per-source health over a period (task 5.8): success rate, error breakdown, data age,
request count and estimated cost, all computed from recorded fetch attempts and observations.

The estimated cost is ``requests × connector_config.estimated_cost_per_request_rial`` (0 when
not configured) — a planning figure for the phase A budget (Q-T4), not an invoice.
"""

import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.collection.models import (
    FetchAttemptRow,
    FetchOutcome,
    ObservationRow,
    Validity,
)
from pricing_assistant.sources.api import (
    SourceRow,
    TrackedOfferRow,
    TrackedOfferStatus,
    connector_config,
)


@dataclass(frozen=True, slots=True)
class SourceHealth:
    source_id: uuid.UUID
    name: str
    status: str
    period_hours: int
    requests: int
    successes: int
    success_rate: float | None
    errors: dict[str, int] = field(default_factory=dict)
    blocked: int = 0
    data_age_median_seconds: int | None = None
    data_age_max_seconds: int | None = None
    offers_without_observation: int = 0
    estimated_cost_rial: int = 0


async def _data_ages(
    session: AsyncSession, source_id: uuid.UUID, now: datetime
) -> tuple[list[int], int]:
    offers = (
        await session.scalars(
            select(TrackedOfferRow.id).where(
                TrackedOfferRow.source_id == source_id,
                TrackedOfferRow.status == TrackedOfferStatus.ACTIVE.value,
            )
        )
    ).all()
    if not offers:
        return [], 0
    latest = {
        offer_id: observed_at
        for offer_id, observed_at in (
            await session.execute(
                select(ObservationRow.tracked_offer_id, func.max(ObservationRow.observed_at))
                .where(
                    ObservationRow.tracked_offer_id.in_(offers),
                    ObservationRow.validity == Validity.VALID.value,
                )
                .group_by(ObservationRow.tracked_offer_id)
            )
        ).all()
    }
    ages = [int((now - observed).total_seconds()) for observed in latest.values()]
    return ages, len(offers) - len(latest)


async def source_health(
    session: AsyncSession, *, hours: int = 24, now: datetime | None = None
) -> list[SourceHealth]:
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    counts: dict[uuid.UUID, dict[str, int]] = {}
    rows = await session.execute(
        select(
            FetchAttemptRow.source_id,
            FetchAttemptRow.outcome,
            FetchAttemptRow.error_class,
            func.count(),
        )
        .where(FetchAttemptRow.finished_at >= since, FetchAttemptRow.finished_at <= now)
        .group_by(FetchAttemptRow.source_id, FetchAttemptRow.outcome, FetchAttemptRow.error_class)
    )
    for source_id, outcome, error_class, count in rows.all():
        bucket = counts.setdefault(source_id, {})
        key = "success" if outcome == FetchOutcome.SUCCESS.value else f"error:{error_class}"
        bucket[key] = bucket.get(key, 0) + int(count)

    report: list[SourceHealth] = []
    for source in (await session.scalars(select(SourceRow).order_by(SourceRow.name))).all():
        bucket = counts.get(source.id, {})
        requests = sum(bucket.values())
        successes = bucket.get("success", 0)
        errors = {k.removeprefix("error:"): v for k, v in bucket.items() if k.startswith("error:")}
        ages, missing = await _data_ages(session, source.id, now)
        cost_per_request = int(
            (await connector_config(session, source.id)).get("estimated_cost_per_request_rial", 0)
        )
        report.append(
            SourceHealth(
                source_id=source.id,
                name=source.name,
                status=source.status,
                period_hours=hours,
                requests=requests,
                successes=successes,
                success_rate=round(successes / requests, 4) if requests else None,
                errors=errors,
                blocked=errors.get("blocked", 0),
                data_age_median_seconds=int(statistics.median(ages)) if ages else None,
                data_age_max_seconds=max(ages) if ages else None,
                offers_without_observation=missing,
                estimated_cost_rial=requests * cost_per_request,
            )
        )
    return report
