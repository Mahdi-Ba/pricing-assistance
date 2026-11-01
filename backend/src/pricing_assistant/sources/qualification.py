"""Phase A source qualification (tasks 6.1, 6.2).

A run fetches every tracked offer of a variant sample (default 20) on cleared candidate sources,
then reports per source: how many sample variants it covers, how many fetches succeeded, how
many offers matched, how fresh the data is, which limits were hit and what it cost. An admin
approves or rejects each source from the report; approval still requires an unrevoked
clearance and moves the source to ``approved``.
"""

import statistics
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, Uuid, func, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.collection.api import FetchAttemptRow, ObservationRow, Validity
from pricing_assistant.collection.events import BrowserFetchRequested, FetchRequested
from pricing_assistant.core.db import Base
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.matching.api import MatchState, current_matches
from pricing_assistant.sources.config import get_config
from pricing_assistant.sources.models import (
    RetrievalMethod,
    SourceRow,
    SourceStatus,
    TrackedOfferRow,
    TrackedOfferStatus,
)
from pricing_assistant.sources.registry import change_status, current_clearance, may_fetch

DEFAULT_SAMPLE_SIZE = 20
LIMIT_ERRORS = frozenset({"blocked", "quota_exhausted"})


class QualificationRunRow(Base):
    __tablename__ = "qualification_run"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    status: Mapped[str] = mapped_column(Text)
    variant_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    source_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_offers: Mapped[int] = mapped_column(Integer)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_by: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


async def start_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    variant_ids: list[uuid.UUID],
    source_ids: list[uuid.UUID],
    now: datetime | None = None,
) -> QualificationRunRow:
    now = now or datetime.now(UTC)
    if not variant_ids or not source_ids:
        raise ValidationFailed("A run needs at least one variant and one source")
    refused: list[str] = []
    sources: list[SourceRow] = []
    for source_id in source_ids:
        source = await session.get(SourceRow, source_id)
        if source is None:
            raise NotFound(f"Source {source_id} not found", message_fa="منبع یافت نشد.")
        if (
            not await may_fetch(session, source)
            or source.status != SourceStatus.UNDER_EVALUATION.value
        ):
            refused.append(source.name)
        sources.append(source)
    if refused:
        raise Conflict(
            f"Sources not cleared or not under evaluation: {', '.join(refused)}",
            code="clearance_missing",
            message_fa=f"این منابع مجوز ثبت‌شده ندارند یا در حال ارزیابی نیستند: {'، '.join(refused)}",
            extra={"sources": refused},
        )
    offers = (
        await session.scalars(
            select(TrackedOfferRow).where(
                TrackedOfferRow.source_id.in_(source_ids),
                TrackedOfferRow.variant_id.in_(variant_ids),
                TrackedOfferRow.status == TrackedOfferStatus.ACTIVE.value,
            )
        )
    ).all()
    by_id = {s.id: s for s in sources}
    run = QualificationRunRow(
        id=new_id(),
        tenant_id=tenant_id,
        status="running",
        variant_ids=variant_ids,
        source_ids=source_ids,
        window_start=now,
        requested_offers=len(offers),
        started_by=actor.username,
    )
    session.add(run)
    await session.flush()
    for offer in offers:
        event_class = (
            BrowserFetchRequested
            if RetrievalMethod(by_id[offer.source_id].method) is RetrievalMethod.RENDERED_PAGE
            else FetchRequested
        )
        await publish(
            session,
            tenant_id=tenant_id,
            event=event_class(tracked_offer_id=offer.id, window_start=now, trigger="qualification"),
        )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.qualification.started",
        target_type="qualification_run",
        target_id=run.id,
        after={
            "variants": len(variant_ids),
            "sources": [s.name for s in sources],
            "offers": len(offers),
        },
    )
    return run


async def _source_report(
    session: AsyncSession, run: QualificationRunRow, source: SourceRow, now: datetime
) -> dict[str, Any]:
    offers = (
        await session.scalars(
            select(TrackedOfferRow).where(
                TrackedOfferRow.source_id == source.id,
                TrackedOfferRow.variant_id.in_(run.variant_ids),
            )
        )
    ).all()
    offer_ids = [o.id for o in offers]
    attempts = (
        await session.scalars(
            select(FetchAttemptRow).where(
                FetchAttemptRow.tracked_offer_id.in_(offer_ids or [uuid.uuid4()]),
                FetchAttemptRow.trigger == "qualification",
                FetchAttemptRow.window_start == run.window_start,
            )
        )
    ).all()
    final = [a for a in attempts if a.final]
    successes = sum(1 for a in final if a.outcome == "success")
    errors: dict[str, int] = {}
    for attempt in attempts:
        if attempt.error_class:
            errors[attempt.error_class] = errors.get(attempt.error_class, 0) + 1
    matches = await current_matches(session, offer_ids)
    matched_variants = {
        o.variant_id
        for o in offers
        if any(
            m.tracked_offer_id == o.id
            and m.state in (MatchState.CONFIRMED.value, MatchState.PROPOSED.value)
            for m in matches
        )
    }
    latest = (
        await session.execute(
            select(ObservationRow.tracked_offer_id, func.max(ObservationRow.observed_at))
            .where(
                ObservationRow.tracked_offer_id.in_(offer_ids or [uuid.uuid4()]),
                ObservationRow.validity == Validity.VALID.value,
            )
            .group_by(ObservationRow.tracked_offer_id)
        )
    ).all()
    ages = [int((now - observed).total_seconds()) for _, observed in latest]
    cost_per_request = int(
        (await get_config(session, source.id)).get("estimated_cost_per_request_rial", 0)
    )
    covered = {o.variant_id for o in offers}
    return {
        "source_id": str(source.id),
        "name": source.name,
        "status": source.status,
        "sample_variants": len(run.variant_ids),
        "variants_tracked": len(covered),
        "fetches": len(attempts),
        "completed_fetches": len(final),
        "extraction_success_rate": round(successes / len(final), 4) if final else None,
        "match_rate": round(len(matched_variants) / len(covered), 4) if covered else None,
        "freshness_median_seconds": int(statistics.median(ages)) if ages else None,
        "limits_encountered": sum(v for k, v in errors.items() if k in LIMIT_ERRORS),
        "errors": errors,
        "cost_rial": len(attempts) * cost_per_request,
    }


async def report(
    session: AsyncSession, run_id: uuid.UUID, *, now: datetime | None = None
) -> QualificationRunRow:
    """Compute the report; mark the run completed once every requested fetch is final."""
    now = now or datetime.now(UTC)
    run = await session.get(QualificationRunRow, run_id, with_for_update=True)
    if run is None:
        raise NotFound("Qualification run not found", message_fa="اجرای ارزیابی یافت نشد.")
    sources = (
        await session.scalars(select(SourceRow).where(SourceRow.id.in_(run.source_ids)))
    ).all()
    per_source = [
        await _source_report(session, run, s, now) for s in sorted(sources, key=lambda s: s.name)
    ]
    finished = sum(s["completed_fetches"] for s in per_source)
    if run.status == "running":
        run.report = {"sources": per_source, "completed_fetches": finished}
        if finished >= run.requested_offers:
            run.status = "completed"
            run.completed_at = now
    return run


async def decide_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    run_id: uuid.UUID,
    source_id: uuid.UUID,
    approve: bool,
    reason: str,
) -> SourceRow:
    run = await session.get(QualificationRunRow, run_id)
    if run is None or source_id not in run.source_ids:
        raise NotFound(
            "Source is not part of this run", message_fa="این منبع در این ارزیابی نبوده است."
        )
    if run.status != "completed":
        raise Conflict("The run has not completed", message_fa="ارزیابی هنوز کامل نشده است.")
    clearance = await current_clearance(session, source_id)
    target = SourceStatus.APPROVED if approve else SourceStatus.REJECTED
    source = await change_status(
        session,
        tenant_id=tenant_id,
        actor=actor,
        source_id=source_id,
        target=target,
        reason=f"{reason} (qualification {run_id})",
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.qualification.decided",
        target_type="source",
        target_id=source_id,
        after={
            "decision": target.value,
            "run_id": str(run_id),
            "clearance_reference": clearance.reference if clearance else None,
            "report": next(
                (
                    s
                    for s in (run.report or {}).get("sources", [])
                    if s["source_id"] == str(source_id)
                ),
                None,
            ),
        },
        reason=reason,
    )
    return source
