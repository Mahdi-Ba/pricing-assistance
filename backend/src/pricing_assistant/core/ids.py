"""Identifier helpers. All entity and event IDs are time-ordered UUIDv7."""

import uuid

from uuid_utils.compat import uuid7


def new_id() -> uuid.UUID:
    return uuid7()
