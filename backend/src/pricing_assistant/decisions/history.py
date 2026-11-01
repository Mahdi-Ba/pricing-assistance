"""Per-variant decision history (task 10.8).

Each recommendation version, oldest first, with the decisions taken on it (corrections
included), each decision's override review, outcome stages and derived status.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.decisions.models import DecisionOutcomeRow, DecisionRow, OverrideReviewRow
from pricing_assistant.decisions.service import DecisionStatus, derive_status
from pricing_assistant.pricing.api import RecommendationRow, recommendations_for_variant


@dataclass(frozen=True, slots=True)
class DecisionView:
    decision: DecisionRow
    review: OverrideReviewRow | None
    outcomes: list[DecisionOutcomeRow]
    status: DecisionStatus
    superseded_by: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class HistoryItem:
    recommendation: RecommendationRow
    decisions: list[DecisionView] = field(default_factory=list)


async def decision_views(
    session: AsyncSession, decisions: list[DecisionRow]
) -> dict[uuid.UUID, DecisionView]:
    ids = [d.id for d in decisions]
    if not ids:
        return {}
    reviews = {
        r.decision_id: r
        for r in (
            await session.scalars(
                select(OverrideReviewRow).where(OverrideReviewRow.decision_id.in_(ids))
            )
        ).all()
    }
    outcomes: dict[uuid.UUID, list[DecisionOutcomeRow]] = defaultdict(list)
    for row in (
        await session.scalars(
            select(DecisionOutcomeRow)
            .where(DecisionOutcomeRow.decision_id.in_(ids))
            .order_by(DecisionOutcomeRow.occurred_at, DecisionOutcomeRow.id)
        )
    ).all():
        outcomes[row.decision_id].append(row)
    successors = {
        d.supersedes_decision_id: d.id
        for d in (
            await session.scalars(
                select(DecisionRow).where(DecisionRow.supersedes_decision_id.in_(ids))
            )
        ).all()
    }
    return {
        d.id: DecisionView(
            decision=d,
            review=reviews.get(d.id),
            outcomes=outcomes[d.id],
            status=derive_status(d, reviews.get(d.id), {o.stage for o in outcomes[d.id]}),
            superseded_by=successors.get(d.id),
        )
        for d in decisions
    }


async def variant_history(session: AsyncSession, variant_id: uuid.UUID) -> list[HistoryItem]:
    recommendations = await recommendations_for_variant(session, variant_id)
    decisions = list(
        (
            await session.scalars(
                select(DecisionRow)
                .where(DecisionRow.variant_id == variant_id)
                .order_by(DecisionRow.created_at, DecisionRow.id)
            )
        ).all()
    )
    views = await decision_views(session, decisions)
    by_recommendation: dict[uuid.UUID, list[DecisionView]] = defaultdict(list)
    for decision in decisions:
        by_recommendation[decision.recommendation_id].append(views[decision.id])
    return [HistoryItem(rec, by_recommendation[rec.id]) for rec in recommendations]
