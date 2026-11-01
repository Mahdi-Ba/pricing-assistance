"""Reporting HTTP API: pilot report, weekly report, match audits, review baselines (13.x).

Reports are read by experts and admins; drawing audit samples, recording audit verdicts and
entering baselines are admin actions. Measured values and targets are separate fields.
"""

import dataclasses
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from pricing_assistant.core.deps import DatabaseDep
from pricing_assistant.core.errors import ValidationFailed
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.iam.api import AdminPrincipal, ExpertPrincipal, actor_of
from pricing_assistant.reporting import audit, pilot, weekly
from pricing_assistant.reporting.models import MatchAuditItemRow

router = APIRouter(route_class=IdempotentRoute, tags=["reporting"])
MAX_PERIOD = timedelta(days=366)


def _plain(value: Any) -> Any:
    """Dataclasses → JSON-ready dicts (UUIDs and datetimes are serialized by FastAPI)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


def _period(start: date, end: date) -> tuple[datetime, datetime]:
    begin = datetime.combine(start, time.min, tzinfo=UTC)
    finish = datetime.combine(end, time.min, tzinfo=UTC) + timedelta(days=1)
    if finish <= begin or finish - begin > MAX_PERIOD:
        raise ValidationFailed(
            "The period must be 1 to 366 days", message_fa="بازه گزارش باید بین ۱ تا ۳۶۶ روز باشد."
        )
    return begin, finish


# --- pilot report ---------------------------------------------------------------------------------


class AccuracyOut(BaseModel):
    reviewed: int
    correct: int
    accuracy_pct: float | None


class MatchAccuracyOut(BaseModel):
    sample_id: uuid.UUID
    period: str
    population: int
    size: int
    overall: AccuracyOut
    target_pct: float


class PilotReportOut(BaseModel):
    start: datetime
    end: datetime
    match_accuracy: MatchAccuracyOut | None
    floor_safety: dict[str, Any]
    evidence_completeness: dict[str, Any]
    review_time: dict[str, Any]


@router.get("/reports/pilot", response_model=PilotReportOut)
async def pilot_report(
    principal: ExpertPrincipal,
    db: DatabaseDep,
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
) -> PilotReportOut:
    begin, finish = _period(start, end)
    async with db.tenant_session(principal.tenant_id) as session:
        sample = await audit.latest_sample(session)
        accuracy = None
        if sample is not None:
            result = await audit.audit_result(session, sample.id)
            accuracy = MatchAccuracyOut(
                sample_id=sample.id,
                period=sample.period,
                population=sample.population,
                size=sample.size,
                overall=AccuracyOut(**dataclasses.asdict(result.overall)),
                target_pct=result.target_pct,
            )
        return PilotReportOut(
            start=begin,
            end=finish,
            match_accuracy=accuracy,
            floor_safety=_plain(await pilot.floor_safety(session, begin, finish)),
            evidence_completeness=_plain(await pilot.evidence_completeness(session, begin, finish)),
            review_time=_plain(await pilot.review_time(session, begin, finish)),
        )


# --- weekly report --------------------------------------------------------------------------------


@router.get("/reports/weekly")
async def weekly_report(
    principal: ExpertPrincipal,
    db: DatabaseDep,
    request: Request,
    week_start: date,
) -> dict[str, Any]:
    start = datetime.combine(week_start, time.min, tzinfo=UTC)
    async with db.tenant_session(principal.tenant_id) as session:
        report = await weekly.weekly_report(
            session,
            principal.tenant_id,
            start,
            llm_prices=request.app.state.settings.llm_cost_rial_per_million_tokens,
        )
    body: dict[str, Any] = _plain(report)
    return body


# --- match audit ----------------------------------------------------------------------------------


class AuditDrawIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    size: Annotated[int, Field(ge=1, le=2_000)] = 200


class AuditItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    match_version_id: uuid.UUID
    category: str
    source_id: uuid.UUID
    confidence_band: str
    verdict: Literal["correct", "incorrect"] | None
    note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None


class AuditOut(BaseModel):
    id: uuid.UUID
    period: str
    population: int
    size: int
    created_by: str
    created_at: datetime
    overall: AccuracyOut
    by_category: dict[str, AccuracyOut]
    by_source: dict[str, AccuracyOut]
    by_band: dict[str, AccuracyOut]
    target_pct: float
    incorrect: list[AuditItemOut]
    items: list[AuditItemOut]


class VerdictIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["correct", "incorrect"]
    note: Annotated[str, StringConstraints(max_length=1_000)] | None = None


def _audit_out(result: audit.AuditResult) -> AuditOut:
    def acc(a: audit.Accuracy) -> AccuracyOut:
        return AccuracyOut(**dataclasses.asdict(a))

    sample = result.sample
    return AuditOut(
        id=sample.id,
        period=sample.period,
        population=sample.population,
        size=sample.size,
        created_by=sample.created_by,
        created_at=sample.created_at,
        overall=acc(result.overall),
        by_category={k: acc(v) for k, v in result.by_category.items()},
        by_source={k: acc(v) for k, v in result.by_source.items()},
        by_band={k: acc(v) for k, v in result.by_band.items()},
        target_pct=result.target_pct,
        incorrect=[AuditItemOut.model_validate(i) for i in result.incorrect],
        items=[AuditItemOut.model_validate(i) for i in result.items],
    )


@router.post("/reports/match-audits", status_code=status.HTTP_201_CREATED, response_model=AuditOut)
async def draw_audit(body: AuditDrawIn, principal: AdminPrincipal, db: DatabaseDep) -> AuditOut:
    async with db.tenant_session(principal.tenant_id) as session:
        sample = await audit.draw_sample(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            period=body.period,
            size=body.size,
        )
        return _audit_out(await audit.audit_result(session, sample.id))


@router.get("/reports/match-audits/{sample_id}", response_model=AuditOut)
async def get_audit(sample_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep) -> AuditOut:
    async with db.tenant_session(principal.tenant_id) as session:
        return _audit_out(await audit.audit_result(session, sample_id))


@router.post("/reports/match-audit-items/{item_id}/verdict", response_model=AuditItemOut)
async def audit_verdict(
    item_id: uuid.UUID, body: VerdictIn, principal: AdminPrincipal, db: DatabaseDep
) -> MatchAuditItemRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await audit.record_verdict(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            item_id=item_id,
            correct=body.verdict == "correct",
            note=body.note,
        )


# --- baselines ------------------------------------------------------------------------------------


class BaselineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    median_minutes: Annotated[float, Field(gt=0, le=600)]
    note: Annotated[str, StringConstraints(max_length=1_000)] | None = None


class BaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category: str
    median_seconds: int
    note: str | None
    entered_by: str
    created_at: datetime


@router.get("/reports/baselines", response_model=list[BaselineOut])
async def list_baselines(principal: ExpertPrincipal, db: DatabaseDep) -> list[Any]:
    async with db.tenant_session(principal.tenant_id) as session:
        return list((await pilot.baselines(session)).values())


@router.put("/reports/baselines/{category}", response_model=BaselineOut)
async def set_baseline(
    category: str, body: BaselineIn, principal: AdminPrincipal, db: DatabaseDep
) -> Any:
    async with db.tenant_session(principal.tenant_id) as session:
        return await pilot.set_baseline(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            category=category,
            median_minutes=body.median_minutes,
            note=body.note,
        )
