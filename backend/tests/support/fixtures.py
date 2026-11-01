"""Access to recorded source fixtures under fixtures/sources/."""

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "sources"


def fixture_text(relative: str) -> str:
    return (FIXTURES / relative).read_text(encoding="utf-8")


def fixture_json(relative: str) -> Any:
    return json.loads(fixture_text(relative))
