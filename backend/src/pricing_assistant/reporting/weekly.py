"""Weekly operational, coverage and verification KPIs (task 13.4, Q-K3).

Each KPI is returned with its sample size, its target (or ``None`` when no target is set) and
the table it was computed from, so the report can show where every figure comes from.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.api import ImportanceTier, list_variants
from pricing_assistant.collection.api import ObservationRow, SourceHealth, source_health
from pricing_assistant.core import tenant_settings
from pricing_assistant.decisions.api import DecisionOutcomeRow, DecisionRow, Stage
from pricing_assistant.llm.api import LLMCallRow
from pricing_assistant.pricing.api import RecommendationRow
from pricing_assistant.reporting.sampling import median, percentile, share
from pricing_assistant.workspace.api import OPEN_STATUSES, load_queue

WEEK = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class Kpi:
    key: str
    value: float | None
    unit: str
    sample: int
    target: float | None
    source: str  # the recorded data the figure is computed from

    @property
    def target_set(self) -> bool:
        return self.target is not None


@dataclass(frozen=True, slots=True)
class Distribution:
    count: int
    median: float | None
    p90: float | None
    max: float | None


def distribution(values: list[float]) -> Distribution:
    return Distribution(
        count=len(values),
        median=median(values),
        p90=percentile(values, 90),
        max=max(values) if values else None,
    )


@dataclass(frozen=True, slots=True)
class LlmUsage:
    task: str
    model: str
    calls: int
    ok: int
    input_tokens: int
    output_tokens: int
    cost_rial: int | None  # None when no price is configured for the model


@dataclass(frozen=True, slots=True)
class WeeklyReport:
    start: datetime
    end: datetime
    sources: list[SourceHealth]
    llm: list[LlmUsage]
    backlog: dict[str, int]
    recommendation_to_decision_seconds: Distribution
    tier_a_coverage: Kpi
    tier_a_data_age_seconds: Distribution
    verification_reliability: Kpi
    site_delay_seconds: Distribution
    channel_delay_seconds: Distribution
    kpis: list[Kpi]


async def _llm_usage(
    session: AsyncSession, start: datetime, end: datetime, prices: dict[str, dict[str, int]]
) -> list[LlmUsage]:
    rows = (
        await session.execute(
            select(
                LLMCallRow.task,
                LLMCallRow.model,
                func.count(),
                func.count().filter(LLMCallRow.result == "ok"),
                func.coalesce(func.sum(LLMCallRow.input_tokens), 0),
                func.coalesce(func.sum(LLMCallRow.output_tokens), 0),
            )
            .where(LLMCallRow.created_at >= start, LLMCallRow.created_at < end)
            .group_by(LLMCallRow.task, LLMCallRow.model)
            .order_by(LLMCallRow.task, LLMCallRow.model)
        )
    ).all()
    usage = []
    for task, model, calls, ok, tokens_in, tokens_out in rows:
        price = prices.get(model)
        cost = (
            round(
                (tokens_in * price.get("input", 0) + tokens_out * price.get("output", 0))
                / 1_000_000
            )
            if price
            else None
        )
        usage.append(
            LlmUsage(task, model, int(calls), int(ok), int(tokens_in), int(tokens_out), cost)
        )
    return usage


async def _decision_latency(session: AsyncSession, start: datetime, end: datetime) -> Distribution:
    rows = (
        await session.execute(
            select(DecisionRow.created_at, RecommendationRow.created_at)
            .join(RecommendationRow, RecommendationRow.id == DecisionRow.recommendation_id)
            .where(
                DecisionRow.created_at >= start,
                DecisionRow.created_at < end,
                DecisionRow.supersedes_decision_id.is_(None),
            )
        )
    ).all()
    return distribution([(d - r).total_seconds() for d, r in rows])


async def _tier_a(
    session: AsyncSession, end: datetime, target: float | None
) -> tuple[Kpi, Distribution]:
    tier_a = [v.id for v in await list_variants(session) if v.importance_tier is ImportanceTier.A]
    current = (
        {
            r.variant_id: r
            for r in (
                await session.scalars(
                    select(RecommendationRow).where(
                        RecommendationRow.superseded_by.is_(None),
                        RecommendationRow.variant_id.in_(tier_a),
                    )
                )
            ).all()
        }
        if tier_a
        else {}
    )
    covered = [v for v in tier_a if v in current and current[v].qualifying_count > 0]
    qualifying = {obs for r in current.values() for obs in r.qualifying_observation_ids}
    newest: dict[uuid.UUID, datetime] = {}
    if qualifying:
        for variant_id, observed in (
            await session.execute(
                select(ObservationRow.variant_id, func.max(ObservationRow.observed_at))
                .where(ObservationRow.id.in_(qualifying))
                .group_by(ObservationRow.variant_id)
            )
        ).all():
            newest[variant_id] = observed
    coverage = Kpi(
        key="tier_a_coverage_pct",
        value=share(len(covered), len(tier_a)),
        unit="%",
        sample=len(tier_a),
        target=target,
        source="recommendation (current, tier A)",
    )
    return coverage, distribution([(end - t).total_seconds() for t in newest.values()])


async def _verification(
    session: AsyncSession, start: datetime, end: datetime, window_minutes: int, target: float | None
) -> tuple[Kpi, Distribution, Distribution]:
    outcomes = (
        await session.scalars(
            select(DecisionOutcomeRow).where(
                DecisionOutcomeRow.decision_id.in_(
                    select(DecisionOutcomeRow.decision_id).where(
                        DecisionOutcomeRow.stage == Stage.REPORTED_DONE.value,
                        DecisionOutcomeRow.occurred_at >= start,
                        DecisionOutcomeRow.occurred_at < end,
                    )
                )
            )
        )
    ).all()
    stages: dict[uuid.UUID, dict[str, DecisionOutcomeRow]] = defaultdict(dict)
    for row in outcomes:
        stages[row.decision_id][row.stage] = row
    reported = len(stages)
    in_window = sum(
        1
        for s in stages.values()
        if Stage.OBSERVED_ON_SITE.value in s
        and (s[Stage.OBSERVED_ON_SITE.value].delay_seconds or 0) <= window_minutes * 60
    )

    def delays(stage: Stage) -> Distribution:
        return distribution(
            [float(s[stage.value].delay_seconds or 0) for s in stages.values() if stage.value in s]
        )

    reliability = Kpi(
        key="verification_reliability_pct",
        value=share(in_window, reported),
        unit="%",
        sample=reported,
        target=target,
        source="decision_outcome (reported_done → observed_on_site within the window)",
    )
    return reliability, delays(Stage.OBSERVED_ON_SITE), delays(Stage.REFLECTED_IN_CHANNEL)


async def weekly_report(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    start: datetime,
    *,
    llm_prices: dict[str, dict[str, int]],
) -> WeeklyReport:
    end = start + WEEK
    as_of = min(end, datetime.now(UTC))  # point-in-time figures for a week still running
    settings = await tenant_settings.load(session, tenant_id)
    targets = settings.kpi_targets
    sources = await source_health(session, hours=int(WEEK.total_seconds() // 3600), now=as_of)
    queue = await load_queue(session, now=as_of)
    backlog: dict[str, int] = defaultdict(int)
    for item in queue:
        if item.status in OPEN_STATUSES:
            backlog[item.status.value] += 1
    coverage, data_age = await _tier_a(session, as_of, targets.tier_a_coverage_pct)
    reliability, site, channel = await _verification(
        session,
        start,
        end,
        settings.verification_window_minutes,
        targets.verification_reliability_pct,
    )
    requests = sum(s.requests for s in sources)
    successes = sum(s.successes for s in sources)
    kpis = [
        coverage,
        Kpi(
            key="tier_a_data_age_p90_minutes",
            value=round(data_age.p90 / 60, 1) if data_age.p90 is not None else None,
            unit="min",
            sample=data_age.count,
            target=targets.tier_a_data_age_p90_minutes,
            source="observation (newest qualifying, tier A)",
        ),
        reliability,
        Kpi(
            key="source_success_rate_pct",
            value=share(successes, requests),
            unit="%",
            sample=requests,
            target=targets.source_success_rate_pct,
            source="fetch_attempt",
        ),
    ]
    return WeeklyReport(
        start=start,
        end=end,
        sources=sources,
        llm=await _llm_usage(session, start, end, llm_prices),
        backlog=dict(backlog),
        recommendation_to_decision_seconds=await _decision_latency(session, start, end),
        tier_a_coverage=coverage,
        tier_a_data_age_seconds=data_age,
        verification_reliability=reliability,
        site_delay_seconds=site,
        channel_delay_seconds=channel,
        kpis=kpis,
    )
