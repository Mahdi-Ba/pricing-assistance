import base64
import os

import pytest
from pydantic import SecretStr

from pricing_assistant.core.crypto import SecretBox, SecretDecryptionError


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def test_round_trip_and_context_binding() -> None:
    box = SecretBox.from_setting(SecretStr(f"1:{_key()}"))
    sealed, version = box.encrypt("api-token-123", context="t1:s1:api_token")
    assert b"api-token-123" not in sealed
    assert box.decrypt(sealed, version=version, context="t1:s1:api_token") == "api-token-123"
    with pytest.raises(SecretDecryptionError):
        box.decrypt(sealed, version=version, context="t2:s1:api_token")


def test_rotation_keeps_old_versions_readable() -> None:
    old_key, new_key = _key(), _key()
    old = SecretBox.from_setting(SecretStr(f"1:{old_key}"))
    sealed, version = old.encrypt("v", context="c")
    rotated = SecretBox.from_setting(SecretStr(f"1:{old_key},2:{new_key}"))
    assert rotated.current_version == 2
    assert rotated.decrypt(sealed, version=version, context="c") == "v"
    assert rotated.encrypt("v", context="c")[1] == 2


def test_wrong_key_length_is_rejected() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SecretBox.from_setting(SecretStr("1:c2hvcnQ="))
