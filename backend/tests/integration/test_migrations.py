import os
import subprocess

import pytest

from pricing_assistant.core.settings import get_settings

from .conftest import BACKEND_DIR

pytestmark = pytest.mark.integration


def _alembic(*args: str) -> None:
    env = dict(os.environ)
    env["PA_DATABASE_OWNER_URL"] = get_settings().database_owner_url.get_secret_value()
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["uv", "run", "alembic", *args],  # noqa: S607
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
    )


def test_upgrade_downgrade_upgrade_roundtrip(migrated: None) -> None:
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
