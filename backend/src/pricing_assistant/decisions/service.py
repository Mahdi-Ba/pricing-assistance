"""Decisions, below-floor overrides and outcome tracking (tasks 10.2–10.6).

Every write appends a row; nothing is updated. A decision is bound to the recommendation version
the expert saw, checked under ``SELECT … FOR UPDATE``. An applied price below the floor in
force needs an admin's approval (``override_review``) before the change may be reported done;
an admin's own below-floor decision is ``self_approved``. Outcome stages are recorded
separately: ``reported_done`` by the expert, ``observed_on_site`` and ``reflected_in_channel``
from our own store and channel observations, and ``verification_overdue`` by a timer.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.audit.api import SYSTEM_ACTOR, AuditActor, record
from pricing_assistant.collection.api import ObservationRow
from pricing_assistant.core import tenant_settings
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.decisions.events import DecisionRecorded, OutcomeReached, OverrideReviewed
from pricing_assistant.decisions.models import (
    ACCEPT_TYPES,
    DecisionOutcomeRow,
    DecisionRow,
    DecisionType,
    OverrideReviewRow,
    Stage,
    Verdict,
)
from pricing_assistant.pricing.api import RecommendationRow

REASON_REQUIRED_FA = "برای ثبت، یادداشت تصمیم را وارد کنید."
OVERRIDE_NOT_APPROVED_FA = "قیمت زیر کف نیازمند تأیید مدیر است."


class DecisionStatus(StrEnum):
    """Where a decision stands; the queue shows these (review-workspace)."""

    DECIDED = "decided"  # تصمیم ثبت شد
    OVERRIDE_PENDING = "override_pending"  # در انتظار تأیید مدیر
    OVERRIDE_REJECTED = "override_rejected"  # back to «نیازمند بررسی»; a new decision is needed
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFICATION_OVERDUE = "verification_overdue"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class DecisionCommand:
    recommendation_id: uuid.UUID
    type: DecisionType
    reason: str
    applied_price_rial: int | None = None
    override_reason: str | None = None
    supersedes_decision_id: uuid.UUID | None = None


async def _lock_decision(session: AsyncSession, decision_id: uuid.UUID) -> None:
    """Serialize commands on one decision for this transaction.

    Decisions are append-only (no UPDATE grant), so ``FOR UPDATE`` is not available; an advisory
    transaction lock does the job, and unique indexes remain the final guard.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"decision:{decision_id}"},
    )


def _not_superseded() -> Select[uuid.UUID | None]:
    """IDs of decisions some other decision supersedes."""
    return select(DecisionRow.supersedes_decision_id).where(
        DecisionRow.supersedes_decision_id.is_not(None)
    )


async def _locked_recommendation(
    session: AsyncSession, recommendation_id: uuid.UUID
) -> RecommendationRow:
    rec = await session.get(RecommendationRow, recommendation_id, with_for_update=True)
    if rec is None:
        raise NotFound("Recommendation not found", message_fa="پیشنهاد قیمت یافت نشد.")
    return rec


def _stale(rec: RecommendationRow) -> Conflict:
    return Conflict(
        "The recommendation changed; review the current version",
        code="recommendation_superseded",
        message_fa="پیشنهاد قیمت تغییر کرده است؛ نسخه جدید را بررسی کنید.",
        extra={"current_recommendation_id": str(rec.superseded_by)},
    )


async def _check_correction(
    session: AsyncSession, original_id: uuid.UUID, rec: RecommendationRow
) -> DecisionRow:
    await _lock_decision(session, original_id)
    original = await session.get(DecisionRow, original_id)
    if original is None:
        raise NotFound("Decision to correct not found", message_fa="تصمیم قبلی یافت نشد.")
    if original.variant_id != rec.variant_id:
        raise ValidationFailed(
            "A correction must concern the same variant",
            message_fa="اصلاح باید برای همان کالا باشد.",
        )
    if await session.scalar(
        select(DecisionRow.id).where(DecisionRow.supersedes_decision_id == original_id)
    ):
        raise Conflict(
            "This decision was already corrected",
            code="decision_superseded",
            message_fa="این تصمیم قبلاً اصلاح شده است؛ آخرین نسخه را اصلاح کنید.",
        )
    # correcting the record of the same recommendation is allowed after it was superseded;
    # a decision on another recommendation must be on the current one
    if rec.id != original.recommendation_id and rec.superseded_by is not None:
        raise _stale(rec)
    return original


async def _check_first_decision(session: AsyncSession, rec: RecommendationRow) -> None:
    if rec.superseded_by is not None:
        raise _stale(rec)
    existing = await session.scalar(
        select(DecisionRow.id).where(
            DecisionRow.recommendation_id == rec.id, DecisionRow.id.not_in(_not_superseded())
        )
    )
    if existing is not None:
        raise Conflict(
            "A decision exists for this recommendation; correct it instead",
            code="already_decided",
            message_fa="برای این پیشنهاد تصمیم ثبت شده است؛ در صورت نیاز آن را اصلاح کنید.",
            extra={"decision_id": str(existing)},
        )


def _check_price(command: DecisionCommand, rec: RecommendationRow) -> None:
    accept = command.type in ACCEPT_TYPES
    if accept and (command.applied_price_rial is None or command.applied_price_rial <= 0):
        raise ValidationFailed(
            "An applied price is required for accept decisions",
            code="applied_price_required",
            message_fa="قیمتی را که در فروشگاه اعمال کرده‌اید وارد کنید.",
        )
    if not accept and command.applied_price_rial is not None:
        raise ValidationFailed(
            "Only accept decisions carry an applied price",
            code="applied_price_not_allowed",
            message_fa="برای رد یا تعویق، قیمت اعمال‌شده وارد نکنید.",
        )
    if command.type is DecisionType.ACCEPT and (
        rec.suggested_price_rial is None or command.applied_price_rial != rec.suggested_price_rial
    ):
        raise ValidationFailed(
            "Accept means the suggested price was applied; use accept_modified otherwise",
            code="accept_requires_suggested_price",
            message_fa="اگر قیمت دیگری اعمال کرده‌اید، «پذیرش با تغییر» را انتخاب کنید.",
        )


async def record_decision(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    is_admin: bool,
    command: DecisionCommand,
) -> DecisionRow:
    reason = command.reason.strip()
    if not reason:
        raise ValidationFailed(
            "A reason is required", code="reason_required", message_fa=REASON_REQUIRED_FA
        )
    rec = await _locked_recommendation(session, command.recommendation_id)
    if command.supersedes_decision_id is not None:
        await _check_correction(session, command.supersedes_decision_id, rec)
    else:
        await _check_first_decision(session, rec)
    _check_price(command, rec)
    applied = command.applied_price_rial
    below = rec.floor_rial is not None and applied is not None and applied < rec.floor_rial
    override_reason = (command.override_reason or "").strip() or None
    if below and override_reason is None:
        raise ValidationFailed(
            "A below-floor price needs an override reason",
            code="override_reason_required",
            message_fa="برای قیمت زیر کف سود، دلیل استثنا را وارد کنید.",
        )
    decision = DecisionRow(
        id=new_id(),
        tenant_id=tenant_id,
        variant_id=rec.variant_id,
        recommendation_id=rec.id,
        type=command.type.value,
        reason=reason,
        applied_price_rial=applied,
        floor_rial=rec.floor_rial,
        below_floor_override=below,
        override_reason=override_reason if below else None,
        supersedes_decision_id=command.supersedes_decision_id,
        actor_subject=actor.subject,
        actor=actor.username,
    )
    session.add(decision)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=DecisionRecorded(
            decision_id=decision.id,
            variant_id=decision.variant_id,
            recommendation_id=rec.id,
            type=decision.type,
            below_floor_override=below,
            supersedes_decision_id=command.supersedes_decision_id,
        ),
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="decision.recorded",
        target_type="decision",
        target_id=decision.id,
        after={
            "recommendation_id": str(rec.id),
            "type": decision.type,
            "applied_price_rial": applied,
            "floor_rial": rec.floor_rial,
            "below_floor_override": below,
            "supersedes_decision_id": str(command.supersedes_decision_id)
            if command.supersedes_decision_id
            else None,
        },
        reason=reason,
    )
    if below:
        if is_admin:
            await _add_review(
                session,
                tenant_id=tenant_id,
                actor=actor,
                decision=decision,
                verdict=Verdict.SELF_APPROVED,
                reason=override_reason or reason,
            )
        else:
            await record(
                session,
                tenant_id=tenant_id,
                actor=actor,
                action="decision.override.requested",
                target_type="decision",
                target_id=decision.id,
                after={"applied_price_rial": applied, "floor_rial": rec.floor_rial},
                reason=override_reason,
            )
    return decision


async def _add_review(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    decision: DecisionRow,
    verdict: Verdict,
    reason: str,
) -> OverrideReviewRow:
    review = OverrideReviewRow(
        id=new_id(),
        tenant_id=tenant_id,
        decision_id=decision.id,
        verdict=verdict.value,
        reason=reason,
        actor_subject=actor.subject,
        actor=actor.username,
    )
    session.add(review)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=OverrideReviewed(
            decision_id=decision.id, variant_id=decision.variant_id, verdict=verdict.value
        ),
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action=f"decision.override.{verdict.value}",
        target_type="decision",
        target_id=decision.id,
        after={
            "applied_price_rial": decision.applied_price_rial,
            "floor_rial": decision.floor_rial,
            "requested_by": decision.actor,
        },
        reason=reason,
    )
    return review


async def _is_superseded(session: AsyncSession, decision_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(DecisionRow.id).where(DecisionRow.supersedes_decision_id == decision_id)
    )
    return found is not None


async def _locked_decision(session: AsyncSession, decision_id: uuid.UUID) -> DecisionRow:
    await _lock_decision(session, decision_id)
    decision = await session.get(DecisionRow, decision_id)
    if decision is None:
        raise NotFound("Decision not found", message_fa="تصمیم یافت نشد.")
    if await _is_superseded(session, decision_id):
        raise Conflict(
            "This decision was corrected; act on the latest version",
            code="decision_superseded",
            message_fa="این تصمیم اصلاح شده است؛ آخرین نسخه را بررسی کنید.",
        )
    return decision


async def review_override(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    decision_id: uuid.UUID,
    approve: bool,
    reason: str,
) -> OverrideReviewRow:
    """Admin approves or rejects a pending below-floor override (admin role checked by the API)."""
    reason = reason.strip()
    if not reason:
        raise ValidationFailed("A reason is required", message_fa="دلیل را وارد کنید.")
    decision = await _locked_decision(session, decision_id)
    if not decision.below_floor_override:
        raise Conflict(
            "This decision has no below-floor override",
            code="no_override",
            message_fa="این تصمیم قیمت زیر کف ندارد.",
        )
    if await session.scalar(
        select(OverrideReviewRow.id).where(OverrideReviewRow.decision_id == decision_id)
    ):
        raise Conflict(
            "The override was already reviewed",
            code="override_already_reviewed",
            message_fa="درباره این استثنا قبلاً تصمیم گرفته شده است.",
        )
    return await _add_review(
        session,
        tenant_id=tenant_id,
        actor=actor,
        decision=decision,
        verdict=Verdict.APPROVED if approve else Verdict.REJECTED,
        reason=reason,
    )


async def _stage(
    session: AsyncSession, decision_id: uuid.UUID, stage: Stage
) -> DecisionOutcomeRow | None:
    row: DecisionOutcomeRow | None = await session.scalar(
        select(DecisionOutcomeRow).where(
            DecisionOutcomeRow.decision_id == decision_id, DecisionOutcomeRow.stage == stage.value
        )
    )
    return row


async def _add_outcome(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    decision: DecisionRow,
    stage: Stage,
    occurred_at: datetime,
    actor: str | None = None,
    observation_id: uuid.UUID | None = None,
    delay_seconds: int | None = None,
) -> DecisionOutcomeRow:
    outcome = DecisionOutcomeRow(
        id=new_id(),
        tenant_id=tenant_id,
        decision_id=decision.id,
        stage=stage.value,
        occurred_at=occurred_at,
        actor=actor,
        observation_id=observation_id,
        delay_seconds=delay_seconds,
    )
    session.add(outcome)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=OutcomeReached(decision_id=decision.id, variant_id=decision.variant_id, stage=stage),
    )
    return outcome


async def report_done(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    decision_id: uuid.UUID,
    now: datetime | None = None,
) -> DecisionOutcomeRow:
    """The expert reports that the price was changed in the store by hand."""
    decision = await _locked_decision(session, decision_id)
    if DecisionType(decision.type) not in ACCEPT_TYPES:
        raise Conflict(
            "Only accepted decisions are reported as done",
            code="not_an_accepted_decision",
            message_fa="فقط تصمیم‌های پذیرش قابل گزارش انجام هستند.",
        )
    if decision.below_floor_override:
        verdict = await session.scalar(
            select(OverrideReviewRow.verdict).where(OverrideReviewRow.decision_id == decision_id)
        )
        if verdict not in (Verdict.APPROVED.value, Verdict.SELF_APPROVED.value):
            raise Conflict(
                "A below-floor price needs an admin's approval first",
                code="override_not_approved",
                message_fa=OVERRIDE_NOT_APPROVED_FA,
            )
    if await _stage(session, decision_id, Stage.REPORTED_DONE) is not None:
        raise Conflict(
            "Already reported as done",
            code="already_reported",
            message_fa="انجام این تغییر قبلاً گزارش شده است.",
        )
    outcome = await _add_outcome(
        session,
        tenant_id=tenant_id,
        decision=decision,
        stage=Stage.REPORTED_DONE,
        occurred_at=now or datetime.now(UTC),
        actor=actor.username,
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="decision.reported_done",
        target_type="decision",
        target_id=decision.id,
        after={"applied_price_rial": decision.applied_price_rial},
    )
    return outcome


async def _awaiting(
    session: AsyncSession, variant_id: uuid.UUID, stage: Stage
) -> list[tuple[DecisionRow, DecisionOutcomeRow]]:
    """Current accepted decisions of the variant that were reported done but lack ``stage``."""
    reached = select(DecisionOutcomeRow.decision_id).where(DecisionOutcomeRow.stage == stage.value)
    rows = await session.execute(
        select(DecisionRow, DecisionOutcomeRow)
        .join(DecisionOutcomeRow, DecisionOutcomeRow.decision_id == DecisionRow.id)
        .where(
            DecisionRow.variant_id == variant_id,
            DecisionOutcomeRow.stage == Stage.REPORTED_DONE.value,
            DecisionRow.id.not_in(_not_superseded()),
            DecisionRow.id.not_in(reached),
        )
    )
    return [(d, o) for d, o in rows.all()]


async def verify_from_observations(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    variant_id: uuid.UUID,
    observation_ids: list[uuid.UUID],
    own_store: bool,
    own_channel: bool,
) -> list[DecisionOutcomeRow]:
    """Match our own store or channel observations against reported price changes (10.5)."""
    if own_store == own_channel:  # neither (competitor) — or an inconsistent event
        return []
    stage = Stage.OBSERVED_ON_SITE if own_store else Stage.REFLECTED_IN_CHANNEL
    pending = await _awaiting(session, variant_id, stage)
    if not pending:
        return []
    observations = (
        await session.scalars(
            select(ObservationRow)
            .where(
                ObservationRow.id.in_(observation_ids),
                ObservationRow.validity == "valid",
                ObservationRow.price_rial.is_not(None),
            )
            .order_by(ObservationRow.observed_at)
        )
    ).all()
    reached: list[DecisionOutcomeRow] = []
    for decision, reported in pending:
        match = next(
            (
                o
                for o in observations
                if o.observed_at >= reported.occurred_at
                and o.price_rial == decision.applied_price_rial
            ),
            None,
        )
        if match is None:
            continue
        reached.append(
            await _add_outcome(
                session,
                tenant_id=tenant_id,
                decision=decision,
                stage=stage,
                occurred_at=match.observed_at,
                observation_id=match.id,
                delay_seconds=int((match.observed_at - reported.occurred_at).total_seconds()),
            )
        )
    return reached


async def mark_overdue(db: Database, *, now: datetime | None = None) -> int:
    """Return reported changes not seen on our site within the window to the queue (10.6)."""
    now = now or datetime.now(UTC)
    marked = 0
    for tenant_id in await db.active_tenant_ids():
        async with db.tenant_session(tenant_id) as session:
            window = (await tenant_settings.load(session, tenant_id)).verification_window_minutes
            closed = select(DecisionOutcomeRow.decision_id).where(
                DecisionOutcomeRow.stage.in_(
                    [Stage.OBSERVED_ON_SITE.value, Stage.VERIFICATION_OVERDUE.value]
                )
            )
            rows = await session.execute(
                select(DecisionRow, DecisionOutcomeRow)
                .join(DecisionOutcomeRow, DecisionOutcomeRow.decision_id == DecisionRow.id)
                .where(
                    DecisionOutcomeRow.stage == Stage.REPORTED_DONE.value,
                    DecisionOutcomeRow.occurred_at <= now - timedelta(minutes=window),
                    DecisionRow.id.not_in(_not_superseded()),
                    DecisionRow.id.not_in(closed),
                )
            )
            for decision, _reported in rows.all():
                await _add_outcome(
                    session,
                    tenant_id=tenant_id,
                    decision=decision,
                    stage=Stage.VERIFICATION_OVERDUE,
                    occurred_at=now,
                )
                await record(
                    session,
                    tenant_id=tenant_id,
                    actor=SYSTEM_ACTOR,
                    action="decision.verification_overdue",
                    target_type="decision",
                    target_id=decision.id,
                    after={"window_minutes": window},
                )
                marked += 1
    return marked


def derive_status(
    decision: DecisionRow, review: OverrideReviewRow | None, stages: set[str]
) -> DecisionStatus:
    if decision.below_floor_override:
        if review is None:
            return DecisionStatus.OVERRIDE_PENDING
        if review.verdict == Verdict.REJECTED.value:
            return DecisionStatus.OVERRIDE_REJECTED
    if Stage.OBSERVED_ON_SITE.value in stages:
        return DecisionStatus.VERIFIED
    if Stage.VERIFICATION_OVERDUE.value in stages:
        return DecisionStatus.VERIFICATION_OVERDUE
    if Stage.REPORTED_DONE.value in stages:
        return DecisionStatus.AWAITING_VERIFICATION
    return DecisionStatus.DECIDED
