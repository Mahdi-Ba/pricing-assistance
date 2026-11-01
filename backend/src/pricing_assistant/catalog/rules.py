"""Versioned profit rules (task 3.8).

Rules exist at three scopes: ``default`` (one per tenant), ``category`` and ``variant``. A
category or variant rule sets only the fields it overrides; unset fields are inherited from the
less specific scope, so the most specific value wins field by field. Every change inserts a new
immutable version; recommendations reference the versions they used.

Ratios are integer basis points (10 000 = 100 %), money is integer Rial, ages are seconds.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.catalog.events import RuleVersionCreated
from pricing_assistant.catalog.models import ImportanceTier, ProductRow, VariantRow
from pricing_assistant.core.db import Base
from pricing_assistant.core.errors import NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id

BP = 10_000


class RuleScope(StrEnum):
    DEFAULT = "default"
    CATEGORY = "category"
    VARIANT = "variant"


@dataclass(frozen=True, slots=True)
class RuleFields:
    """One rule version's values. ``None`` means "inherit from the less specific scope"."""

    min_margin_bp: int | None = None
    fee_rate_bp: int | None = None
    vat_rate_bp: int | None = None
    ceiling_rial: int | None = None
    undercut_step_rial: int | None = None
    hold_tolerance_bp: int | None = None
    rounding_step_rial: int | None = None
    max_data_age_a_seconds: int | None = None
    max_data_age_b_seconds: int | None = None
    max_data_age_c_seconds: int | None = None
    outlier_threshold_bp: int | None = None
    min_qualifying_offers: int | None = None
    # {source_id: [allowed seller names]}; {} or a source missing from the map = all sellers.
    competitor_set: dict[str, list[str]] | None = None

    def overlay(self, more_specific: "RuleFields") -> "RuleFields":
        changes = {
            f.name: getattr(more_specific, f.name)
            for f in fields(self)
            if getattr(more_specific, f.name) is not None
        }
        return replace(self, **changes)

    def as_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# Every default-scope rule must set these; ceiling and competitor_set stay optional.
REQUIRED_DEFAULT_FIELDS = tuple(
    f.name for f in fields(RuleFields) if f.name not in {"ceiling_rial", "competitor_set"}
)

# Starting values offered to admins (business-questions Q-P2, Q-P3, Q-P4, Q-S4, Q-S5).
# The VAT rate deliberately has no suggestion: it must be set explicitly (Q-D2).
SUGGESTED_DEFAULTS = RuleFields(
    min_margin_bp=1_000,
    fee_rate_bp=0,
    undercut_step_rial=500_000,
    hold_tolerance_bp=100,
    rounding_step_rial=100_000,
    max_data_age_a_seconds=2 * 3600,
    max_data_age_b_seconds=4 * 3600,
    max_data_age_c_seconds=24 * 3600,
    outlier_threshold_bp=1_500,
    min_qualifying_offers=1,
)


@dataclass(frozen=True, slots=True)
class ResolvedRule:
    """Fully resolved rule for one variant, with the versions it was built from."""

    min_margin_bp: int
    fee_rate_bp: int
    vat_rate_bp: int
    ceiling_rial: int | None
    undercut_step_rial: int
    hold_tolerance_bp: int
    rounding_step_rial: int
    max_data_age_seconds: dict[ImportanceTier, int]
    outlier_threshold_bp: int
    min_qualifying_offers: int
    competitor_set: dict[str, list[str]]
    version_ids: tuple[uuid.UUID, ...]

    def allows_seller(self, source_id: uuid.UUID, seller: str | None) -> bool:
        allowed = self.competitor_set.get(str(source_id))
        if not allowed:
            return True
        return seller is not None and seller.strip().casefold() in {
            s.strip().casefold() for s in allowed
        }


class ProfitRuleVersionRow(Base):
    __tablename__ = "profit_rule_version"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    scope: Mapped[str] = mapped_column(Text)
    scope_key: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    min_margin_bp: Mapped[int | None] = mapped_column(Integer)
    fee_rate_bp: Mapped[int | None] = mapped_column(Integer)
    vat_rate_bp: Mapped[int | None] = mapped_column(Integer)
    ceiling_rial: Mapped[int | None] = mapped_column(BigInteger)
    undercut_step_rial: Mapped[int | None] = mapped_column(BigInteger)
    hold_tolerance_bp: Mapped[int | None] = mapped_column(Integer)
    rounding_step_rial: Mapped[int | None] = mapped_column(BigInteger)
    max_data_age_a_seconds: Mapped[int | None] = mapped_column(Integer)
    max_data_age_b_seconds: Mapped[int | None] = mapped_column(Integer)
    max_data_age_c_seconds: Mapped[int | None] = mapped_column(Integer)
    outlier_threshold_bp: Mapped[int | None] = mapped_column(Integer)
    min_qualifying_offers: Mapped[int | None] = mapped_column(Integer)
    competitor_set: Mapped[dict[str, list[str]] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def to_fields(self) -> RuleFields:
        return RuleFields(**{f.name: getattr(self, f.name) for f in fields(RuleFields)})


def _bp(name: str, value: int | None, *, allow_full: bool = False) -> list[str]:
    upper = BP if allow_full else BP - 1
    if value is not None and not 0 <= value <= upper:
        return [f"{name} must be between 0 and {upper} basis points"]
    return []


def _positive(name: str, value: int | None) -> list[str]:
    if value is not None and value <= 0:
        return [f"{name} must be positive"]
    return []


def field_errors(values: RuleFields) -> list[str]:
    """Range checks for the values a single version sets."""
    errors = [
        *_bp("min_margin_bp", values.min_margin_bp),
        *_bp("fee_rate_bp", values.fee_rate_bp),
        *_bp("vat_rate_bp", values.vat_rate_bp, allow_full=True),
        *_bp("hold_tolerance_bp", values.hold_tolerance_bp),
        *_bp("outlier_threshold_bp", values.outlier_threshold_bp),
    ]
    for name in (
        "ceiling_rial",
        "undercut_step_rial",
        "rounding_step_rial",
        "max_data_age_a_seconds",
        "max_data_age_b_seconds",
        "max_data_age_c_seconds",
        "min_qualifying_offers",
    ):
        errors += _positive(name, getattr(values, name))
    if values.competitor_set is not None:
        for source_id, sellers in values.competitor_set.items():
            try:
                uuid.UUID(source_id)
            except ValueError:
                errors.append(f"competitor_set key {source_id!r} is not a source id")
            if not all(isinstance(s, str) and s.strip() for s in sellers):
                errors.append(f"competitor_set[{source_id}] must list seller names")
    return errors


def _set(value: int | None) -> int:
    if value is None:  # unreachable: resolve() checks REQUIRED_DEFAULT_FIELDS first
        raise ValueError("rule field unexpectedly unset")
    return value


def resolve(chain: list[tuple[uuid.UUID, RuleFields]]) -> ResolvedRule | None:
    """Merge versions ordered default → category → variant. None without a complete default."""
    if not chain:
        return None
    merged = chain[0][1]
    if any(getattr(merged, name) is None for name in REQUIRED_DEFAULT_FIELDS):
        return None
    for _, more_specific in chain[1:]:
        merged = merged.overlay(more_specific)
    return ResolvedRule(
        min_margin_bp=_set(merged.min_margin_bp),
        fee_rate_bp=_set(merged.fee_rate_bp),
        vat_rate_bp=_set(merged.vat_rate_bp),
        ceiling_rial=merged.ceiling_rial,
        undercut_step_rial=_set(merged.undercut_step_rial),
        hold_tolerance_bp=_set(merged.hold_tolerance_bp),
        rounding_step_rial=_set(merged.rounding_step_rial),
        max_data_age_seconds={
            ImportanceTier.A: _set(merged.max_data_age_a_seconds),
            ImportanceTier.B: _set(merged.max_data_age_b_seconds),
            ImportanceTier.C: _set(merged.max_data_age_c_seconds),
        },
        outlier_threshold_bp=_set(merged.outlier_threshold_bp),
        min_qualifying_offers=_set(merged.min_qualifying_offers),
        competitor_set=merged.competitor_set or {},
        version_ids=tuple(version_id for version_id, _ in chain),
    )


async def latest_version(
    session: AsyncSession, scope: RuleScope, scope_key: str | None
) -> ProfitRuleVersionRow | None:
    query = select(ProfitRuleVersionRow).where(ProfitRuleVersionRow.scope == scope.value)
    query = query.where(
        ProfitRuleVersionRow.scope_key.is_(None)
        if scope_key is None
        else ProfitRuleVersionRow.scope_key == scope_key
    )
    row: ProfitRuleVersionRow | None = await session.scalar(
        query.order_by(ProfitRuleVersionRow.version.desc()).limit(1)
    )
    return row


async def current_versions(session: AsyncSession) -> list[ProfitRuleVersionRow]:
    """The latest version for every (scope, scope_key)."""
    rows = await session.scalars(
        select(ProfitRuleVersionRow)
        .ext(distinct_on(ProfitRuleVersionRow.scope, ProfitRuleVersionRow.scope_key))
        .order_by(
            ProfitRuleVersionRow.scope,
            ProfitRuleVersionRow.scope_key,
            ProfitRuleVersionRow.version.desc(),
        )
    )
    return list(rows.all())


async def history(
    session: AsyncSession, scope: RuleScope, scope_key: str | None
) -> list[ProfitRuleVersionRow]:
    query = select(ProfitRuleVersionRow).where(ProfitRuleVersionRow.scope == scope.value)
    query = query.where(
        ProfitRuleVersionRow.scope_key.is_(None)
        if scope_key is None
        else ProfitRuleVersionRow.scope_key == scope_key
    )
    return list((await session.scalars(query.order_by(ProfitRuleVersionRow.version.desc()))).all())


async def _chain(
    session: AsyncSession, category: str, variant_id: uuid.UUID
) -> list[tuple[uuid.UUID, RuleFields]]:
    chain: list[tuple[uuid.UUID, RuleFields]] = []
    for scope, key in (
        (RuleScope.DEFAULT, None),
        (RuleScope.CATEGORY, category),
        (RuleScope.VARIANT, str(variant_id)),
    ):
        version = await latest_version(session, scope, key)
        if version is not None:
            chain.append((version.id, version.to_fields()))
    return chain


async def resolve_for_variant(session: AsyncSession, variant_id: uuid.UUID) -> ResolvedRule | None:
    category = await session.scalar(
        select(ProductRow.category)
        .join(VariantRow, VariantRow.product_id == ProductRow.id)
        .where(VariantRow.id == variant_id)
    )
    if category is None:
        raise NotFound("Variant not found", message_fa="کالا یافت نشد.")
    return resolve(await _chain(session, category, variant_id))


async def resolve_for_variants(
    session: AsyncSession, variants: Iterable[tuple[uuid.UUID, str]]
) -> dict[uuid.UUID, ResolvedRule | None]:
    """Resolved rules for many ``(variant_id, category)`` pairs with one query."""
    latest = {(v.scope, v.scope_key): v for v in await current_versions(session)}
    resolved: dict[uuid.UUID, ResolvedRule | None] = {}
    for variant_id, category in variants:
        chain = [
            (version.id, version.to_fields())
            for key in (
                (RuleScope.DEFAULT.value, None),
                (RuleScope.CATEGORY.value, category),
                (RuleScope.VARIANT.value, str(variant_id)),
            )
            if (version := latest.get(key)) is not None
        ]
        resolved[variant_id] = resolve(chain)
    return resolved


async def _check_combinations(
    session: AsyncSession, scope: RuleScope, scope_key: str | None, proposed: RuleFields
) -> list[str]:
    """Margin plus fees must stay below 100 % for every combination the change affects."""
    current = {(v.scope, v.scope_key): v.to_fields() for v in await current_versions(session)}
    current[(scope.value, scope_key)] = proposed
    default = current.get((RuleScope.DEFAULT.value, None))
    if default is None:
        return ["define the default rule first"]
    errors: list[str] = []
    categories = {key: f for (s, key), f in current.items() if s == RuleScope.CATEGORY.value}
    combos: list[RuleFields] = [default, *(default.overlay(f) for f in categories.values())]
    if scope is RuleScope.VARIANT and scope_key is not None:
        category = await session.scalar(
            select(ProductRow.category)
            .join(VariantRow, VariantRow.product_id == ProductRow.id)
            .where(VariantRow.id == uuid.UUID(scope_key))
        )
        if category is None:
            return ["variant does not exist"]
        base = default.overlay(categories.get(category, RuleFields()))
        combos.append(base.overlay(proposed))
    for combo in combos:
        if (combo.min_margin_bp or 0) + (combo.fee_rate_bp or 0) >= BP:
            errors.append("min_margin_bp + fee_rate_bp must be below 10000")
            break
    return errors


async def create_version(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    scope: RuleScope,
    scope_key: str | None,
    values: RuleFields,
    reason: str | None,
) -> ProfitRuleVersionRow:
    if (scope is RuleScope.DEFAULT) != (scope_key is None):
        raise ValidationFailed("scope_key is required for category and variant rules")
    if scope is RuleScope.VARIANT and scope_key is not None:
        try:
            scope_key = str(uuid.UUID(scope_key))
        except ValueError as exc:
            raise ValidationFailed("Variant rule key must be a variant id") from exc
    errors = field_errors(values)
    if scope is RuleScope.DEFAULT:
        missing = [name for name in REQUIRED_DEFAULT_FIELDS if getattr(values, name) is None]
        errors += [f"{name} is required in the default rule" for name in missing]
    if not errors:
        errors += await _check_combinations(session, scope, scope_key, values)
    if errors:
        vat_missing = "vat_rate_bp is required in the default rule" in errors
        raise ValidationFailed(
            "; ".join(errors),
            code="invalid_rule",
            message_fa=(
                "نرخ مالیات بر ارزش افزوده (vat_rate_bp) باید صریحاً تعیین شود."
                if vat_missing
                else "مقادیر قاعده سود معتبر نیست."
            ),
            extra={"errors": errors},
        )
    previous = await latest_version(session, scope, scope_key)
    row = ProfitRuleVersionRow(
        id=new_id(),
        tenant_id=tenant_id,
        scope=scope.value,
        scope_key=scope_key,
        version=(previous.version + 1) if previous else 1,
        reason=reason,
        created_by=actor.username,
        **values.as_dict(),
    )
    session.add(row)
    await session.flush()
    await publish(
        session,
        tenant_id=tenant_id,
        event=RuleVersionCreated(rule_version_id=row.id, scope=scope.value, scope_key=scope_key),
    )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="rule.version.created",
        target_type="profit_rule",
        target_id=f"{scope.value}:{scope_key or '-'}",
        before=previous.to_fields().as_dict() if previous else None,
        after={"version": row.version, **values.as_dict()},
        reason=reason,
    )
    return row


async def resolve_versions(
    session: AsyncSession, version_ids: list[uuid.UUID]
) -> ResolvedRule | None:
    """Rebuild a resolved rule from specific (immutable) versions, ordered default → variant."""
    if not version_ids:
        return None
    rows = {
        r.id: r
        for r in (
            await session.scalars(
                select(ProfitRuleVersionRow).where(ProfitRuleVersionRow.id.in_(version_ids))
            )
        ).all()
    }
    return resolve([(vid, rows[vid].to_fields()) for vid in version_ids if vid in rows])
