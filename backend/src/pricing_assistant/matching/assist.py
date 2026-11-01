"""Optional LLM help in matching (D8 steps 3 and 6, tasks 8.1–8.4).

Both steps only run when the LLM port is enabled, and both only ever *add information for a
human*: extracted attributes fill gaps the rules left (tagged ``llm``), and a match proposal
can at most move an offer to ``proposed``. Nothing here confirms a match. Every failure —
disabled, budget exhausted, invalid answer, provider error — leaves the rule-based result.
"""

import uuid
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from pricing_assistant.catalog.api import VariantInfo, list_variants
from pricing_assistant.collection.api import ObservationRow
from pricing_assistant.llm.api import (
    PUBLIC_ATTRIBUTE_KEYS,
    CandidateVariant,
    ExtractRequest,
    LLMPort,
    MatchRequest,
)
from pricing_assistant.matching.extract import Attributes, from_json, merge_llm, rule_part, to_json
from pricing_assistant.matching.models import DecisionSource, MatchState, OfferAttributesRow
from pricing_assistant.matching.scoring import (
    BP,
    REQUIRED_FOR_MATCH,
    Assessment,
    VariantProfile,
    block_candidates,
    profile_from_catalog,
)

LLM_MIN_CONFIDENCE = 0.7
LLM_MAX_CONFIDENCE_BP = 9_000  # an LLM proposal never looks as certain as an identifier match
MAX_OTHER_CANDIDATES = 4
MAX_OFFER_TEXT = 2_000


def needs_extraction(attrs: Attributes) -> bool:
    return any(name not in attrs for name in REQUIRED_FOR_MATCH)


async def fill_attributes(
    llm: LLMPort,
    tenant_id: uuid.UUID,
    *,
    title: str | None,
    attrs: Attributes,
    latest: OfferAttributesRow | None,
    known_models: list[str],
) -> Attributes:
    """Rule attributes plus LLM values for the gaps; one call per distinct rule result."""
    if not title or not llm.enabled or not needs_extraction(attrs):
        return attrs
    if latest is not None and rule_part(latest.attributes) == to_json(attrs):
        # same rule result as last time: reuse what the model said then (or nothing)
        return from_json(latest.attributes)
    result = await llm.extract_attributes(
        tenant_id, ExtractRequest(offer_text=title[:MAX_OFFER_TEXT])
    )
    if not result.ok or result.value is None:
        return attrs
    return merge_llm(attrs, result.value.model_dump(), known_models=known_models)


def _candidate(info: VariantInfo) -> CandidateVariant:
    public = {
        key: value
        for key, value in info.attributes.items()
        if key in PUBLIC_ATTRIBUTE_KEYS
        and isinstance(value, str | int)
        and not isinstance(value, bool)
    }
    return CandidateVariant(
        id=info.id, brand=info.brand, model=info.model, name=info.product_name, attributes=public
    )


def needs_proposal(result: Assessment) -> bool:
    """Only offers held back for missing attributes; never overrides a mismatch."""
    return (
        result.state is MatchState.NEEDS_REVIEW
        and bool(result.flags)
        and all(flag.startswith("missing:") for flag in result.flags)
    )


def _profile(info: VariantInfo) -> VariantProfile:
    return profile_from_catalog(
        info.id,
        brand=info.brand,
        model=info.model,
        mpn=info.mpn,
        gtin=info.gtin,
        attributes=info.attributes,
    )


async def propose(
    session: AsyncSession,
    llm: LLMPort,
    tenant_id: uuid.UUID,
    *,
    attributes: OfferAttributesRow,
    attrs: Attributes,
    variant: VariantInfo,
    result: Assessment,
) -> tuple[Assessment, str | None]:
    """Ask the model which candidate the offer is; returns the (possibly) updated assessment."""
    if not llm.enabled or not needs_proposal(result) or attributes.observation_id is None:
        return result, None
    observation = await session.get(ObservationRow, attributes.observation_id)
    if observation is None or not observation.title:
        return result, None
    catalog = {v.id: v for v in await list_variants(session) if v.id != variant.id}
    others = block_candidates(attrs, [_profile(v) for v in catalog.values()])
    candidates = [_candidate(variant)] + [
        _candidate(catalog[p.id]) for p in others[:MAX_OTHER_CANDIDATES]
    ]
    answer = await llm.propose_match(
        tenant_id,
        MatchRequest(offer_text=observation.title[:MAX_OFFER_TEXT], candidates=candidates),
    )
    if not answer.ok or answer.value is None:
        return result, None
    proposal = answer.value
    reason = f"LLM: {proposal.rationale}"[:1_000]
    if proposal.variant_id == variant.id and proposal.confidence >= LLM_MIN_CONFIDENCE:
        confidence = min(int(proposal.confidence * BP), LLM_MAX_CONFIDENCE_BP)
        return (
            Assessment(
                variant.id,
                MatchState.PROPOSED,
                confidence,
                [*result.flags, "llm_proposal"],
                DecisionSource.LLM,
            ),
            reason,
        )
    if proposal.variant_id is not None and proposal.variant_id != variant.id:
        return replace(result, flags=[*result.flags, f"llm_suggests:{proposal.variant_id}"]), reason
    return result, None
