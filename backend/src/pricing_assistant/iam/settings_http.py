"""Admin API for per-tenant operational settings."""

from typing import Any

from fastapi import APIRouter

from pricing_assistant.audit.api import record
from pricing_assistant.core import tenant_settings
from pricing_assistant.core.deps import DatabaseDep
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.iam.guards import AdminPrincipal, ExpertPrincipal, actor_of

router = APIRouter(route_class=IdempotentRoute, tags=["settings"])


@router.get("/settings", response_model=tenant_settings.TenantSettings)
async def get_settings(
    principal: ExpertPrincipal, db: DatabaseDep
) -> tenant_settings.TenantSettings:
    async with db.tenant_session(principal.tenant_id) as session:
        return await tenant_settings.load(session, principal.tenant_id)


@router.patch("/settings", response_model=tenant_settings.TenantSettings)
async def patch_settings(
    changes: dict[str, Any], principal: AdminPrincipal, db: DatabaseDep
) -> tenant_settings.TenantSettings:
    async with db.tenant_session(principal.tenant_id) as session:
        before, after = await tenant_settings.update(
            session, principal.tenant_id, changes, principal.username
        )
        await record(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            action="tenant.settings.changed",
            target_type="tenant_settings",
            target_id=principal.tenant_id,
            before=before.model_dump(),
            after=after.model_dump(),
        )
    return after
