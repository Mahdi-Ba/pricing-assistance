import uuid

from pricing_assistant.catalog.models import ImportanceTier
from pricing_assistant.catalog.rules import (
    SUGGESTED_DEFAULTS,
    RuleFields,
    field_errors,
    resolve,
)

DEFAULT = SUGGESTED_DEFAULTS.overlay(RuleFields(vat_rate_bp=1_000))
IDS = [uuid.uuid4() for _ in range(3)]


def test_default_alone_resolves_completely() -> None:
    rule = resolve([(IDS[0], DEFAULT)])
    assert rule is not None
    assert rule.min_margin_bp == 1_000
    assert rule.max_data_age_seconds == {
        ImportanceTier.A: 7_200,
        ImportanceTier.B: 14_400,
        ImportanceTier.C: 86_400,
    }
    assert rule.ceiling_rial is None
    assert rule.competitor_set == {}
    assert rule.version_ids == (IDS[0],)


def test_category_overrides_only_the_fields_it_sets() -> None:
    rule = resolve([(IDS[0], DEFAULT), (IDS[1], RuleFields(min_margin_bp=1_200))])
    assert rule is not None
    assert rule.min_margin_bp == 1_200
    assert rule.undercut_step_rial == 500_000


def test_variant_overrides_category() -> None:
    rule = resolve(
        [
            (IDS[0], DEFAULT),
            (IDS[1], RuleFields(min_margin_bp=1_200, ceiling_rial=120_000_000)),
            (IDS[2], RuleFields(min_margin_bp=900)),
        ]
    )
    assert rule is not None
    assert (rule.min_margin_bp, rule.ceiling_rial) == (900, 120_000_000)
    assert rule.version_ids == tuple(IDS)


def test_default_without_vat_does_not_resolve() -> None:
    assert resolve([(IDS[0], SUGGESTED_DEFAULTS)]) is None
    assert resolve([]) is None


def test_seller_allow_list_per_source() -> None:
    source = uuid.uuid4()
    rule = resolve([(IDS[0], DEFAULT.overlay(RuleFields(competitor_set={str(source): ["Lion"]})))])
    assert rule is not None
    assert rule.allows_seller(source, " lion ")
    assert not rule.allows_seller(source, "Other")
    assert not rule.allows_seller(source, None)
    assert rule.allows_seller(uuid.uuid4(), "anyone")


def test_field_ranges_are_checked() -> None:
    errors = field_errors(
        RuleFields(min_margin_bp=10_000, rounding_step_rial=0, competitor_set={"x": [""]})
    )
    assert any("min_margin_bp" in e for e in errors)
    assert any("rounding_step_rial" in e for e in errors)
    assert any("competitor_set" in e for e in errors)
