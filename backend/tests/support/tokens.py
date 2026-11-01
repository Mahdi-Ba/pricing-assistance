"""Signs test access tokens with a throwaway RSA key and serves the matching JWKS."""

import json
import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from pricing_assistant.iam.api import JwksCache, TokenValidator

ISSUER = "https://idp.test/realms/tunoo"
AUDIENCE = "pricing-api"
KID = "test-key-1"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks() -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def make_validator() -> TokenValidator:
    async def fetch() -> dict[str, Any]:
        return jwks()

    return TokenValidator(issuer=ISSUER, audience=AUDIENCE, jwks=JwksCache(fetch, ttl_seconds=600))


def issue_token(
    *,
    tenant_id: uuid.UUID,
    roles: list[str],
    subject: str = "user-1",
    username: str = "pilot-expert",
    audience: str = AUDIENCE,
    issuer: str = ISSUER,
    # test modules mint tokens once at import; the full integration suite runs longer than 5 min
    expires_in: int = 3600,
    signed_by_other_key: bool = False,
    extra: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "preferred_username": username,
        "iat": now,
        "exp": now + expires_in,
        "tenant_id": str(tenant_id),
        "roles": roles,
        **(extra or {}),
    }
    key = _OTHER_KEY if signed_by_other_key else _PRIVATE_KEY
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})
