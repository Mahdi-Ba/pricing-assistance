"""No price write-back (spec pricing-decisions: Integration scope check; task 10.7).

1. Route inventory: every state-changing API route is listed below after review. Each one only
   changes this system's own records; none of them calls a store or channel. A new mutating
   route fails this test until it is reviewed and added.
2. Connector configuration schemas accept read scopes only.
3. Outbound HTTP from the collection side is GET only (static check of the source code).
"""

import ast
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from pricing_assistant.app import create_app
from pricing_assistant.sources.connectors import torob_shop_api

REVIEWED_MUTATING_ROUTES = {
    ("POST", "/api/v1/catalog/cost-components"),
    ("POST", "/api/v1/catalog/cost-components/{component_id}/deactivate"),
    ("POST", "/api/v1/catalog/costs/{cost_record_id}/review"),
    ("POST", "/api/v1/catalog/imports"),
    ("POST", "/api/v1/decisions/{decision_id}/override-review"),
    ("POST", "/api/v1/decisions/{decision_id}/reported-done"),  # records a manual change
    ("POST", "/api/v1/extraction-rules/{rule_version_id}/review"),
    ("POST", "/api/v1/matches/{match_version_id}/decision"),
    ("POST", "/api/v1/observations/{observation_id}/outlier-confirmation"),
    ("POST", "/api/v1/qualification-runs"),
    ("POST", "/api/v1/qualification-runs/{run_id}/sources/{source_id}/decision"),
    ("POST", "/api/v1/recommendations/{recommendation_id}/decisions"),
    ("POST", "/api/v1/recommendations/{recommendation_id}/replay"),
    ("POST", "/api/v1/reports/match-audit-items/{item_id}/verdict"),
    ("POST", "/api/v1/reports/match-audits"),
    ("PUT", "/api/v1/reports/baselines/{category}"),
    ("POST", "/api/v1/review-sessions"),
    ("POST", "/api/v1/review-sessions/{session_id}/activity"),
    ("POST", "/api/v1/review-sessions/{session_id}/close"),
    ("PUT", "/api/v1/rules/category/{category}"),
    ("PUT", "/api/v1/rules/default"),
    ("PUT", "/api/v1/rules/variant/{variant_id}"),
    ("PATCH", "/api/v1/settings"),
    ("POST", "/api/v1/sources"),
    ("PATCH", "/api/v1/sources/{source_id}"),
    ("DELETE", "/api/v1/sources/{source_id}"),
    ("POST", "/api/v1/sources/{source_id}/clearances"),
    ("POST", "/api/v1/sources/{source_id}/clearances/revoke"),
    ("PUT", "/api/v1/sources/{source_id}/connector-config"),
    ("POST", "/api/v1/sources/{source_id}/extraction-rules"),
    ("POST", "/api/v1/sources/{source_id}/extraction-rules/suggest"),
    ("POST", "/api/v1/sources/{source_id}/offer-url-suggestions"),
    ("POST", "/api/v1/sources/{source_id}/samples"),
    ("DELETE", "/api/v1/sources/{source_id}/secrets/{name}"),
    ("PUT", "/api/v1/sources/{source_id}/secrets/{name}"),
    ("PATCH", "/api/v1/sources/{source_id}/settings"),
    ("POST", "/api/v1/sources/{source_id}/status"),
    ("POST", "/api/v1/tracked-offers"),
    ("POST", "/api/v1/tracked-offers/{tracked_offer_id}/pause"),
    ("POST", "/api/v1/tracked-offers/{tracked_offer_id}/recheck"),
    ("POST", "/api/v1/tracked-offers/{tracked_offer_id}/review"),
}
SRC = Path(__file__).resolve().parents[2] / "src" / "pricing_assistant"
OUTBOUND_PACKAGES = ("sources", "collection")
WRITE_METHODS = {"post", "put", "patch", "delete"}
# reviewed exceptions: (file, call) — none of them reaches a store or channel
ALLOWED_CALLS = {
    ("retention.py", "store.delete"),  # our own evidence object storage (MinIO/S3) purge
    ("registry.py", "session.delete"),  # database row of a never-used candidate source
}


def _mutating_routes() -> set[tuple[str, str]]:
    paths = create_app().openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if method not in {"get", "head", "options", "parameters"}
    }


def test_every_mutating_route_is_reviewed() -> None:
    routes = _mutating_routes()
    assert routes - REVIEWED_MUTATING_ROUTES == set(), "new mutating route: review and list it"
    assert REVIEWED_MUTATING_ROUTES - routes == set(), "listed route no longer exists"


def test_no_route_names_an_external_price_write() -> None:
    suspicious = ("push", "publish", "sync", "write-back", "apply-price", "store-price", "channel")
    assert not [p for _, p in _mutating_routes() if any(word in p for word in suspicious)]


def _config_models() -> list[type[BaseModel]]:
    return [
        value
        for value in vars(torob_shop_api).values()
        if isinstance(value, type)
        and issubclass(value, BaseModel)
        and "scopes" in value.model_fields
    ]


def test_connector_config_schemas_offer_read_scopes_only() -> None:
    models = _config_models()
    assert models
    for model in models:
        schema = model.model_json_schema()["properties"]["scopes"]
        assert schema["items"] == {"const": "read", "type": "string"} or schema["items"].get(
            "enum"
        ) == ["read"]


@pytest.mark.parametrize("scope", ["write", "price:write", "products.update", "admin"])
def test_write_scopes_are_rejected(scope: str) -> None:
    for model in _config_models():
        with pytest.raises(ValidationError):
            model.model_validate({"base_url": "https://api.example.ir", "scopes": [scope]})


def _outbound_calls() -> list[tuple[str, int, str]]:
    """(file, line, problem) for any non-GET HTTP call in the collection-side packages."""
    problems = []
    for package in OUTBOUND_PACKAGES:
        for path in (SRC / package).rglob("*.py"):
            if path.name == "http.py":  # inbound FastAPI routes, not outbound calls
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                name = node.func.attr
                if (path.name, ast.unparse(node.func)) in ALLOWED_CALLS:
                    continue
                if name in WRITE_METHODS:
                    problems.append((path.name, node.lineno, f".{name}(...)"))
                if name in {"stream", "request", "build_request"} and node.args:
                    first = node.args[0]
                    if not (isinstance(first, ast.Constant) and first.value == "GET"):
                        problems.append((path.name, node.lineno, f".{name}({ast.unparse(first)})"))
    return problems


def test_collection_side_sends_get_requests_only() -> None:
    assert _outbound_calls() == []
