"""Effective cost (task 3.7) and review of held cost versions (task 3.11).

Effective cost = purchase cost in force (excluding recoverable input VAT) + the fixed per-unit
components configured for the variant's category (or for all categories). Percentage fees are
not costs here; they are rule rates applied in the floor formula.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.catalog.events import CostChanged
from pricing_assistant.catalog.importing import current_cost
from pricing_assistant.catalog.models import (
    CostRecordRow,
    CostRecordState,
    CostStatus,
    ProductRow,
    VariantRow,
)
from pricing_assistant.core.db import Base
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id


class CostComponentRow(Base):
    """A fixed per-unit cost (freight, customs, packaging...). Immutable once created; an edit is
    a deactivation plus a new component."""

    __tablename__ = "cost_component"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    name: Mapped[str] = mapped_column(Text)
    amount_rial: Mapped[int] = mapped_column(BigInteger)
    category: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deactivated_by: Mapped[str | None] = mapped_column(Text)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True, slots=True)
class EffectiveCost:
    variant_id: uuid.UUID
    cost_record_id: uuid.UUID
    purchase_cost_rial: int
    components_rial: int
    component_ids: tuple[uuid.UUID, ...]

    @property
    def total_rial(self) -> int:
        return self.purchase_cost_rial + self.components_rial


async def _category_of(session: AsyncSession, variant_id: uuid.UUID) -> str:
    category = await session.scalar(
        select(ProductRow.category)
        .join(VariantRow, VariantRow.product_id == ProductRow.id)
        .where(VariantRow.id == variant_id)
    )
    if category is None:
        raise NotFound("Variant not found", message_fa="کالا یافت نشد.")
    return category


async def active_components(
    session: AsyncSession, category: str | None = None
) -> list[CostComponentRow]:
    query = select(CostComponentRow).where(CostComponentRow.active.is_(True))
    if category is not None:
        query = query.where(
            or_(CostComponentRow.category.is_(None), CostComponentRow.category == category)
        )
    return list((await session.scalars(query.order_by(CostComponentRow.created_at))).all())


async def effective_cost(session: AsyncSession, variant_id: uuid.UUID) -> EffectiveCost | None:
    """None when the variant has no valid positive cost in force (``cost_missing``)."""
    in_force = await current_cost(session, variant_id)
    if in_force is None or in_force.purchase_cost_rial <= 0:
        return None
    components = await active_components(session, await _category_of(session, variant_id))
    return EffectiveCost(
        variant_id=variant_id,
        cost_record_id=in_force.id,
        purchase_cost_rial=in_force.purchase_cost_rial,
        components_rial=sum(c.amount_rial for c in components),
        component_ids=tuple(c.id for c in components),
    )


async def _variants_in(session: AsyncSession, category: str | None) -> list[uuid.UUID]:
    query = select(VariantRow.id)
    if category is not None:
        query = query.join(ProductRow, VariantRow.product_id == ProductRow.id).where(
            ProductRow.category == category
        )
    return list((await session.scalars(query)).all())


async def add_component(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    name: str,
    amount_rial: int,
    category: str | None,
) -> CostComponentRow:
    if amount_rial < 0:
        raise ValidationFailed("Amount must not be negative", message_fa="مبلغ نمی‌تواند منفی باشد.")
    component = CostComponentRow(
        id=new_id(),
        tenant_id=tenant_id,
        name=name,
        amount_rial=amount_rial,
        category=category,
        created_by=actor.username,
    )
    session.add(component)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="catalog.cost_component.created",
        target_type="cost_component",
        target_id=component.id,
        after={"name": name, "amount_rial": amount_rial, "category": category},
    )
    await _publish_components_changed(session, tenant_id, category)
    return component


async def deactivate_component(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    component_id: uuid.UUID,
    reason: str,
) -> CostComponentRow:
    component = await session.get(CostComponentRow, component_id, with_for_update=True)
    if component is None:
        raise NotFound("Cost component not found", message_fa="جزء هزینه یافت نشد.")
    if not component.active:
        raise Conflict(
            "Cost component is already inactive", message_fa="این جزء هزینه قبلاً غیرفعال شده است."
        )
    component.active = False
    component.deactivated_by = actor.username
    component.deactivated_at = datetime.now(UTC)
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="catalog.cost_component.deactivated",
        target_type="cost_component",
        target_id=component.id,
        before={"active": True},
        after={"active": False},
        reason=reason,
    )
    await _publish_components_changed(session, tenant_id, component.category)
    return component


async def _publish_components_changed(
    session: AsyncSession, tenant_id: uuid.UUID, category: str | None
) -> None:
    variant_ids = await _variants_in(session, category)
    if variant_ids:
        await publish(
            session,
            tenant_id=tenant_id,
            event=CostChanged(variant_ids=variant_ids, reason="cost_components_changed"),
        )


async def review_held_cost(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    cost_record_id: uuid.UUID,
    confirm: bool,
    reason: str,
) -> CostRecordRow:
    """Confirm (put in force) or reject a cost version held as ``suspect_unit``."""
    if not reason.strip():
        raise ValidationFailed("A reason is required", message_fa="دلیل را وارد کنید.")
    held = await session.get(CostRecordRow, cost_record_id, with_for_update=True)
    if held is None:
        raise NotFound("Cost record not found", message_fa="رکورد هزینه یافت نشد.")
    if held.state != CostRecordState.HELD.value:
        raise Conflict(
            "Only held cost records can be reviewed", message_fa="این هزینه در انتظار تأیید نیست."
        )
    newer = await session.scalar(
        select(CostRecordRow.id).where(
            CostRecordRow.variant_id == held.variant_id,
            CostRecordRow.created_at > held.created_at,
        )
    )
    if confirm and newer is not None:
        raise Conflict(
            "A newer cost version exists; this held value can no longer be confirmed",
            message_fa="هزینه جدیدتری ثبت شده است؛ این مقدار دیگر قابل تأیید نیست.",
        )
    held.state = (CostRecordState.CONFIRMED if confirm else CostRecordState.REJECTED).value
    held.reviewed_by = actor.username
    held.reviewed_at = datetime.now(UTC)
    held.review_reason = reason
    await session.flush()
    if confirm:
        variant = await session.get(VariantRow, held.variant_id, with_for_update=True)
        if variant is not None:
            variant.cost_status = CostStatus.OK.value
        await publish(
            session,
            tenant_id=tenant_id,
            event=CostChanged(variant_ids=[held.variant_id], reason="held_cost_confirmed"),
        )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="catalog.cost.confirmed" if confirm else "catalog.cost.rejected",
        target_type="cost_record",
        target_id=held.id,
        before={"state": CostRecordState.HELD.value},
        after={"state": held.state, "purchase_cost_rial": held.purchase_cost_rial},
        reason=reason,
    )
    return held


async def cost_history(session: AsyncSession, variant_id: uuid.UUID) -> list[CostRecordRow]:
    return list(
        (
            await session.scalars(
                select(CostRecordRow)
                .where(CostRecordRow.variant_id == variant_id)
                .order_by(CostRecordRow.created_at.desc(), CostRecordRow.id.desc())
            )
        ).all()
    )


async def effective_cost_from_refs(
    session: AsyncSession, cost_record_id: uuid.UUID | None, component_ids: list[uuid.UUID]
) -> int | None:
    """Effective cost as it was, from the referenced cost version and components."""
    if cost_record_id is None:
        return None
    cost = await session.get(CostRecordRow, cost_record_id)
    if cost is None:
        return None
    amounts = (
        (
            await session.scalars(
                select(CostComponentRow.amount_rial).where(CostComponentRow.id.in_(component_ids))
            )
        ).all()
        if component_ids
        else []
    )
    return cost.purchase_cost_rial + sum(amounts)
