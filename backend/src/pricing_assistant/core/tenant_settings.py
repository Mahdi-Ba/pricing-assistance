"""Per-tenant operational settings that admins may change at runtime.

One validated JSON document per tenant. Missing keys fall back to the defaults below, so new
settings need no data migration.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base
from pricing_assistant.core.errors import ValidationFailed

Percent = Annotated[float, Field(ge=0, le=100)]


class KpiTargets(BaseModel):
    """Targets for the extra KPIs; unset (None) until they are defined after phase A (Q-K3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tier_a_coverage_pct: Percent | None = None
    tier_a_data_age_p90_minutes: Annotated[int, Field(ge=1)] | None = None
    verification_reliability_pct: Percent | None = None
    source_success_rate_pct: Percent | None = None


class TenantSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recheck_daily_budget_per_user: Annotated[int, Field(ge=0, le=1000)] = 50
    verification_window_minutes: Annotated[int, Field(ge=5, le=7 * 24 * 60)] = 120
    evidence_retention_days: Annotated[int, Field(ge=1, le=3650)] = 90
    observation_retention_days: Annotated[int, Field(ge=30, le=36500)] | None = None
    kpi_targets: KpiTargets = KpiTargets()


class TenantSettingRow(Base):
    __tablename__ = "tenant_setting"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), primary_key=True)
    values: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_by: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def load(session: AsyncSession, tenant_id: uuid.UUID) -> TenantSettings:
    row = await session.get(TenantSettingRow, tenant_id)
    return TenantSettings.model_validate(row.values) if row else TenantSettings()


async def update(
    session: AsyncSession, tenant_id: uuid.UUID, changes: dict[str, Any], updated_by: str
) -> tuple[TenantSettings, TenantSettings]:
    """Apply ``changes``; return (before, after). Unknown keys or invalid values are rejected."""
    before = await load(session, tenant_id)
    try:
        after = TenantSettings.model_validate({**before.model_dump(), **changes})
    except ValidationError as exc:
        raise ValidationFailed(
            "Invalid settings",
            code="invalid_settings",
            message_fa="مقادیر تنظیمات معتبر نیست.",
            extra={"errors": exc.errors(include_url=False, include_context=False)},
        ) from exc
    await session.execute(
        insert(TenantSettingRow)
        .values(tenant_id=tenant_id, values=after.model_dump(), updated_by=updated_by)
        .on_conflict_do_update(
            index_elements=[TenantSettingRow.tenant_id],
            set_={"values": after.model_dump(), "updated_by": updated_by, "updated_at": func.now()},
        )
    )
    return before, after
