"""Runbooks and the phase-gate checklist stay consistent with the repository (tasks 14.5, 15.5).

Every phase-gate item must cite existing business questions and evidence that resolves to a real
document, API path or workspace page; every relative link in the runbooks must resolve.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNBOOKS = ROOT / "docs" / "runbooks"
QUESTIONS = ROOT / "openspec/changes/add-pricing-assistant-mvp/business-questions.md"
OPENAPI = ROOT / "web" / "openapi.json"
WEB_APP = ROOT / "web" / "src" / "app" / "(workspace)"
LINK = re.compile(r"\]\(([^)#]+)(#[^)]*)?\)")
API_PATH = re.compile(r"`(?:GET |POST |PUT |PATCH |DELETE )?(/api/v1/[^`?\s]+)")
UI_PATH = re.compile(r"\(`(/[a-z/]+)`")


def _question_ids() -> set[str]:
    return set(re.findall(r"^### (Q-[A-Z]+\d+)\.", QUESTIONS.read_text(encoding="utf-8"), re.M))


def _api_paths() -> list[re.Pattern[str]]:
    paths = json.loads(OPENAPI.read_text(encoding="utf-8"))["paths"]
    return [re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", p) + "$") for p in paths]


def _gate_rows() -> list[str]:
    text = (RUNBOOKS / "phase-gates.md").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if re.match(r"^\| [ABC]\d+ \|", line)]


def test_every_gate_item_cites_existing_business_questions() -> None:
    known = _question_ids()
    rows = _gate_rows()
    assert len(rows) >= 15
    for row in rows:
        cited = set(re.findall(r"Q-[A-Z]+\d+", row))
        assert cited, row
        assert cited <= known, (row, cited - known)


def test_every_gate_item_has_resolvable_evidence() -> None:
    api = _api_paths()
    for row in _gate_rows():
        evidence = row.split("|")[4]
        resolved = []
        for link, _ in LINK.findall(evidence):
            resolved.append((RUNBOOKS / link).resolve().exists())
        for path in API_PATH.findall(evidence):
            resolved.append(any(p.match(path) for p in api))
        for page in UI_PATH.findall(evidence):
            resolved.append((WEB_APP / page.strip("/") / "page.tsx").exists())
        assert resolved, f"no evidence reference: {row}"
        assert all(resolved), f"unresolved evidence: {row}"


@pytest.mark.parametrize(
    "doc", [*sorted(RUNBOOKS.glob("*.md")), ROOT / "docs" / "deployment.md"], ids=lambda p: p.name
)
def test_runbook_links_resolve(doc: Path) -> None:
    for link, _ in LINK.findall(doc.read_text(encoding="utf-8")):
        if link.startswith(("http://", "https://")):
            continue
        assert (doc.parent / link).resolve().exists(), f"{doc.name}: {link}"


def test_runbook_api_paths_exist() -> None:
    api = _api_paths()
    for doc in RUNBOOKS.glob("*.md"):
        for path in re.findall(
            r"(/api/v1/[A-Za-z0-9_\-/<>{}.-]+)", doc.read_text(encoding="utf-8")
        ):
            normalized = re.sub(r"<[^>]+>", "x", path).rstrip(".")
            assert any(p.match(normalized) for p in api), f"{doc.name}: {path}"
