"""Public interface of the `iam` module.

Other modules may import only this file and `events.py`.
"""

from pricing_assistant.iam.guards import (
    AdminPrincipal,
    AnyPrincipal,
    ExpertPrincipal,
    actor_of,
    require_roles,
)
from pricing_assistant.iam.http import get_principal
from pricing_assistant.iam.oidc import JwksCache, TokenValidator, http_jwks_fetcher
from pricing_assistant.iam.principal import Principal, Role

__all__ = [
    "AdminPrincipal",
    "AnyPrincipal",
    "ExpertPrincipal",
    "JwksCache",
    "Principal",
    "Role",
    "TokenValidator",
    "actor_of",
    "get_principal",
    "http_jwks_fetcher",
    "require_roles",
]
