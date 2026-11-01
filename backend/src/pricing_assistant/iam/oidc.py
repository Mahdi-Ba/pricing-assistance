"""OIDC access-token validation against the identity provider's JWKS."""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

from pricing_assistant.core.errors import AuthenticationRequired
from pricing_assistant.core.logging import get_logger
from pricing_assistant.iam.principal import Principal, Role

ALLOWED_ALGORITHMS = ("RS256", "PS256", "ES256")
_MIN_REFRESH_INTERVAL_SECONDS = 30.0

JwksFetcher = Callable[[], Awaitable[dict[str, Any]]]
log = get_logger(__name__)


def http_jwks_fetcher(url: str, *, timeout: float = 5.0) -> JwksFetcher:
    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            return body

    return fetch


class JwksCache:
    """Caches signing keys; refreshes on expiry or on an unknown ``kid`` (rate-limited)."""

    def __init__(self, fetch: JwksFetcher, *, ttl_seconds: float) -> None:
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        async with self._lock:
            if time.monotonic() - self._fetched_at < _MIN_REFRESH_INTERVAL_SECONDS and self._keys:
                return
            jwks = PyJWKSet.from_dict(await self._fetch())
            self._keys = {key.key_id: key for key in jwks.keys if key.key_id}
            self._fetched_at = time.monotonic()

    async def get(self, kid: str) -> PyJWK:
        expired = time.monotonic() - self._fetched_at > self._ttl
        if expired or kid not in self._keys:
            try:
                await self._refresh()
            except (httpx.HTTPError, jwt.PyJWKSetError) as exc:
                log.warning("oidc.jwks_refresh_failed", error=type(exc).__name__)
                if kid not in self._keys:
                    raise AuthenticationRequired("Signing keys unavailable") from exc
        key = self._keys.get(kid)
        if key is None:
            raise AuthenticationRequired("Unknown signing key")
        return key


class TokenValidator:
    def __init__(
        self, *, issuer: str, audience: str, jwks: JwksCache, leeway_seconds: int = 30
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks = jwks
        self._leeway = leeway_seconds

    async def validate(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise AuthenticationRequired("Malformed token") from exc
        if header.get("alg") not in ALLOWED_ALGORITHMS or not header.get("kid"):
            raise AuthenticationRequired("Unsupported token")
        key = await self._jwks.get(str(header["kid"]))
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationRequired("Token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationRequired("Invalid token") from exc
        return _principal_from_claims(claims)


def _principal_from_claims(claims: dict[str, Any]) -> Principal:
    try:
        tenant_id = uuid.UUID(str(claims["tenant_id"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationRequired("Token has no valid tenant") from exc
    raw_roles = claims.get("roles") or []
    if not isinstance(raw_roles, list):
        raise AuthenticationRequired("Invalid roles claim")
    known = {role.value for role in Role}
    roles = frozenset(Role(r) for r in raw_roles if isinstance(r, str) and r in known)
    return Principal(
        subject=str(claims["sub"]),
        username=str(claims.get("preferred_username") or claims["sub"]),
        tenant_id=tenant_id,
        roles=roles,
    )
