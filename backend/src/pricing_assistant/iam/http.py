"""FastAPI dependencies for authentication."""

from fastapi import Request

from pricing_assistant.core.errors import AuthenticationRequired
from pricing_assistant.iam.oidc import TokenValidator
from pricing_assistant.iam.principal import Principal

_BEARER_CHALLENGE = {"WWW-Authenticate": 'Bearer realm="pricing-api"'}


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationRequired("Missing bearer token", headers=_BEARER_CHALLENGE)
    return token.strip()


async def get_principal(request: Request) -> Principal:
    """Validate the bearer token once per request and cache the principal on the request."""
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    validator: TokenValidator = request.app.state.token_validator
    try:
        principal = await validator.validate(bearer_token(request))
    except AuthenticationRequired as exc:
        exc.headers = {**_BEARER_CHALLENGE, **exc.headers}
        raise
    request.state.principal = principal
    return principal
