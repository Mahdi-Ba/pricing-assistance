import uuid

from pricing_assistant.matching.extract import extract
from pricing_assistant.matching.models import DecisionSource, MatchState
from pricing_assistant.matching.scoring import (
    VariantProfile,
    assess,
    best_candidates,
    block_candidates,
    gtin_valid,
)

SSD = VariantProfile(
    id=uuid.uuid4(),
    brand="Samsung",
    model="990 PRO",
    mpn="MZ-V9P1T0BW",
    gtin="8806094215038",
    capacity="1TB",
    warranty_provider="آواژنگ",
    warranty_months=36,
)
GPU = VariantProfile(
    id=uuid.uuid4(),
    brand="ASUS",
    model="RTX 4060",
    capacity="8GB",
    warranty_provider="آواژنگ",
    warranty_months=36,
)
KNOWN = ["990 PRO", "980 PRO"]


def test_gtin_check_digit() -> None:
    assert gtin_valid("8806094215038")
    assert not gtin_valid("8806094215039")
    assert not gtin_valid("12345")


def test_exact_identifier_with_all_equal_is_auto_confirmed() -> None:
    offer = extract(
        "SSD سامسونگ 990 PRO 1TB",
        conditions={"warranty": "گارانتی ۳۶ ماهه آواژنگ"},
        identifiers={"mpn": "MZ-V9P1T0BW"},
        known_models=KNOWN,
    )
    result = assess(offer, SSD)
    assert result.state is MatchState.CONFIRMED
    assert result.decided_by is DecisionSource.RULE
    assert result.flags == []


def test_invalid_gtin_is_not_auto_confirmed() -> None:
    offer = extract(
        "SSD سامسونگ 990 PRO 1TB",
        conditions={"warranty": "گارانتی ۳۶ ماهه آواژنگ"},
        identifiers={"gtin13": "8806094215039"},  # wrong check digit
        known_models=KNOWN,
    )
    variant = VariantProfile(
        id=SSD.id,
        brand="Samsung",
        model="990 PRO",
        gtin="8806094215039",
        capacity="1TB",
        warranty_provider="آواژنگ",
        warranty_months=36,
    )
    assert assess(offer, variant).state is MatchState.PROPOSED


def test_identifier_without_known_warranty_is_only_proposed() -> None:
    offer = extract("Samsung 990 PRO 1TB", identifiers={"mpn": "MZ-V9P1T0BW"}, known_models=KNOWN)
    assert assess(offer, SSD).state is MatchState.PROPOSED


def test_different_warranty_needs_review() -> None:
    offer = extract(
        "کارت گرافیک ایسوس RTX 4060 8GB",
        conditions={"warranty": "گارانتی ۱۸ ماهه سازگار ارقام"},
    )
    result = assess(offer, GPU)
    assert result.state is MatchState.NEEDS_REVIEW
    assert "condition_mismatch:warranty" in result.flags


def test_instalment_and_used_are_condition_mismatches() -> None:
    offer = extract("ASUS RTX 4060 8GB کارکرده", conditions={"payment": "اقساطی"})
    result = assess(offer, GPU)
    assert result.state is MatchState.NEEDS_REVIEW
    assert {"condition_mismatch:condition", "condition_mismatch:payment"} <= set(result.flags)


def test_identity_mismatch_is_fatal() -> None:
    offer = extract("Samsung 980 PRO 1TB", known_models=KNOWN)
    result = assess(offer, SSD)
    assert result.state is MatchState.NEEDS_REVIEW
    assert "identity_mismatch:model" in result.flags
    assert result.confidence_bp <= 4_000


def test_llm_proposal_is_never_confirmed() -> None:
    offer = extract(
        "SSD سامسونگ 990 PRO 1TB",
        conditions={"warranty": "گارانتی ۳۶ ماهه آواژنگ"},
        identifiers={"mpn": "MZ-V9P1T0BW"},
        known_models=KNOWN,
    )
    result = assess(offer, SSD, proposed_by=DecisionSource.LLM)
    assert result.state is MatchState.PROPOSED
    assert result.decided_by is DecisionSource.LLM


def test_blocking_and_ranking() -> None:
    other = VariantProfile(id=uuid.uuid4(), brand="Samsung", model="990 PRO", capacity="2TB")
    offer = extract("Samsung 990 PRO 1TB", known_models=KNOWN)
    assert {v.id for v in block_candidates(offer, [SSD, GPU, other])} == {SSD.id, other.id}
    ranked = best_candidates(offer, [SSD, GPU, other])
    assert ranked[0].variant_id == SSD.id


def test_frequency_and_generation_compare_by_value() -> None:
    offer = extract("رم کینگستون DDR5 32GB 5600MHz", known_models=["DDR5"])
    variant = VariantProfile(
        uuid.uuid4(),
        brand="Kingston",
        model="DDR5",
        capacity="32GB",
        generation="5",
        frequency="5600",
    )
    result = assess(offer, variant)
    assert not [f for f in result.flags if f.startswith("identity_mismatch")]
    other = VariantProfile(
        uuid.uuid4(), brand="Kingston", model="DDR5", capacity="32GB", frequency="6000"
    )
    assert "identity_mismatch:frequency" in assess(offer, other).flags
