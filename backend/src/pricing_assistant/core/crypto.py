"""Authenticated encryption for secrets stored in the database (AES-256-GCM).

Ciphertexts are bound to their context (tenant, owner, name) through associated data, so a
value copied to another row or tenant fails to decrypt. Keys are versioned for rotation.
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

_NONCE_BYTES = 12
_KEY_BYTES = 32


class SecretDecryptionError(Exception):
    pass


def parse_keys(spec: SecretStr) -> dict[int, bytes]:
    keys: dict[int, bytes] = {}
    for entry in spec.get_secret_value().split(","):
        version, _, encoded = entry.strip().partition(":")
        key = base64.b64decode(encoded)
        if len(key) != _KEY_BYTES:
            raise ValueError(f"encryption key version {version} must be 32 bytes")
        keys[int(version)] = key
    if not keys:
        raise ValueError("no encryption keys configured")
    return keys


class SecretBox:
    def __init__(self, keys: dict[int, bytes]) -> None:
        self._keys = keys
        self.current_version = max(keys)

    @classmethod
    def from_setting(cls, spec: SecretStr) -> "SecretBox":
        return cls(parse_keys(spec))

    def encrypt(self, plaintext: str, *, context: str) -> tuple[bytes, int]:
        nonce = os.urandom(_NONCE_BYTES)
        sealed = AESGCM(self._keys[self.current_version]).encrypt(
            nonce, plaintext.encode(), context.encode()
        )
        return nonce + sealed, self.current_version

    def decrypt(self, ciphertext: bytes, *, version: int, context: str) -> str:
        key = self._keys.get(version)
        if key is None:
            raise SecretDecryptionError(f"key version {version} is not configured")
        try:
            plain = AESGCM(key).decrypt(
                ciphertext[:_NONCE_BYTES], ciphertext[_NONCE_BYTES:], context.encode()
            )
        except InvalidTag as exc:
            raise SecretDecryptionError("ciphertext does not match its context or key") from exc
        return plain.decode()
