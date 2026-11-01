"""Role-based authorization guards. Denied attempts are written to the audit log."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from pricing_assistant.audit.api import AuditActor, AuditOutcome, record
from pricing_assistant.core.db import Database
from pricing_assistant.core.errors import PermissionDenied
from pricing_assistant.core.logging import get_logger
from pricing_assistant.iam.http import get_principal
from pricing_assistant.iam.principal import Principal, Role

log = get_logger(__name__)


def actor_of(principal: Principal) -> AuditActor:
    return AuditActor(subject=principal.subject, username=principal.username)


def require_roles(*roles: Role) -> Callable[..., Awaitable[Principal]]:
    """Dependency that admits principals holding any of ``roles``."""
    if not roles:
        raise ValueError("require_roles needs at least one role")
    required = sorted(role.value for role in roles)

    async def guard(
        request: Request, principal: Annotated[Principal, Depends(get_principal)]
    ) -> Principal:
        if principal.has_any_role(*roles):
            return principal
        db: Database = request.app.state.db
        async with db.tenant_session(principal.tenant_id) as session:
            await record(
                session,
                tenant_id=principal.tenant_id,
                actor=actor_of(principal),
                action="authorization.denied",
                target_type="endpoint",
                target_id=f"{request.method} {request.url.path}",
                after={"required_roles": required, "roles": sorted(principal.roles)},
                outcome=AuditOutcome.DENIED,
            )
        log.warning(
            "authorization.denied", path=request.url.path, required=required, user=principal.subject
        )
        raise PermissionDenied(f"Requires role: {', '.join(required)}")

    return guard


AdminPrincipal = Annotated[Principal, Depends(require_roles(Role.ADMIN))]
ExpertPrincipal = Annotated[Principal, Depends(require_roles(Role.EXPERT, Role.ADMIN))]
AnyPrincipal = Annotated[Principal, Depends(get_principal)]
