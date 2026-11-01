import json

import pytest

from pricing_assistant.matching.extract import attributes_hash, extract, model_key
from pricing_assistant.matching.models import AttributeSource
from tests.support.fixtures import FIXTURES

KNOWN_MODELS = [
    "990 PRO",
    "980 PRO",
    "870 EVO",
    "SN850X",
    "SN770",
    "KC3000",
    "NV2",
    "P3 Plus",
    "T500",
    "LEGEND 960",
]
GOLDEN = [
    json.loads(line)
    for line in (FIXTURES.parent / "matching" / "golden_titles.jsonl")
    .read_text("utf-8")
    .splitlines()
]


def test_golden_set_has_at_least_100_titles() -> None:
    assert len(GOLDEN) >= 100


@pytest.mark.parametrize("case", GOLDEN, ids=[str(i) for i in range(len(GOLDEN))])
def test_golden_titles(case: dict[str, object]) -> None:
    attrs = extract(str(case["title"]), known_models=KNOWN_MODELS)
    expected = case["expected"]
    assert isinstance(expected, dict)
    actual = {key: attrs[key].value for key in expected if key in attrs}
    assert actual == expected, case["title"]


def test_title_normalized_scenario_records_sources() -> None:
    attrs = extract(
        "حافظه SSD سامسونگ 990 PRO ظرفیت 1 ترابایت گارانتی ۳۶ ماهه",
        identifiers={"mpn": "mz-v9p1t0bw"},
        known_models=KNOWN_MODELS,
    )
    assert attrs["brand"].value == "Samsung"
    assert attrs["model"].value == "990 PRO"
    assert attrs["capacity"].value == "1TB"
    assert attrs["warranty_months"].value == 36
    assert attrs["brand"].source is AttributeSource.RULE
    assert attrs["mpn"].value == "MZ-V9P1T0BW"
    assert attrs["mpn"].source is AttributeSource.STRUCTURED_DATA


def test_seller_conditions_override_title_defaults() -> None:
    attrs = extract(
        "کارت گرافیک ایسوس RTX 4060",
        conditions={"warranty": "گارانتی ۱۸ ماهه سازگار ارقام", "payment": "اقساطی"},
        identifiers={"gtin13": "4711387-123456"},
    )
    assert attrs["warranty_provider"].value == "سازگار ارقام"
    assert attrs["warranty_months"].value == 18
    assert attrs["payment"].value == "instalment"
    assert attrs["gtin"].value == "4711387123456"


def test_hash_ignores_provenance_but_not_values() -> None:
    a = extract("Samsung 990 PRO 1TB", known_models=KNOWN_MODELS)
    b = extract("سامسونگ 990PRO 1 ترابایت", known_models=KNOWN_MODELS)
    c = extract("Samsung 990 PRO 2TB", known_models=KNOWN_MODELS)
    assert attributes_hash(a) == attributes_hash(b)
    assert attributes_hash(a) != attributes_hash(c)


def test_model_key() -> None:
    assert model_key("990 PRO") == model_key("990-pro") == "990pro"
