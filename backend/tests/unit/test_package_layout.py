import importlib

import pytest

MODULES = [
    "catalog",
    "sources",
    "collection",
    "matching",
    "pricing",
    "decisions",
    "workspace",
    "llm",
    "iam",
    "audit",
    "reporting",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_exposes_public_interface(module: str) -> None:
    for part in ("api", "events"):
        imported = importlib.import_module(f"pricing_assistant.{module}.{part}")
        assert imported.__doc__
