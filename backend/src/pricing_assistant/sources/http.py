"""Admin HTTP API for sources, clearances, connector configuration and tracked offers."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, status
from sqlalchemy import select

from pricing_assistant.core.crypto import SecretBox
from pricing_assistant.core.deps import DatabaseDep
from pricing_assistant.core.errors import PermissionDenied
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.core.uploads import read_limited
from pricing_assistant.iam.api import AdminPrincipal, ExpertPrincipal, Role, actor_of
from pricing_assistant.llm.api import LLMDep
from pricing_assistant.sources import config, offers, qualification, registry, suggestions
from pricing_assistant.sources import rules as extraction_rules
from pricing_assistant.sources.models import (
    ExtractionRuleVersionRow,
    RuleOrigin,
    SourceClearanceRow,
    SourceRow,
    TrackedOfferRow,
)
from pricing_assistant.sources.schemas import (
    ClearanceIn,
    ClearanceOut,
    ConnectorConfigIn,
    ExtractionRuleIn,
    ExtractionRuleOut,
    PauseIn,
    QualificationDecisionIn,
    QualificationRunIn,
    QualificationRunOut,
    RevokeIn,
    RuleReviewIn,
    SampleOut,
    SecretIn,
    SourceDeleteIn,
    SourceDetailOut,
    SourceIn,
    SourceOut,
    SourceSettingsIn,
    SourceUpdateIn,
    StatusChangeIn,
    SuggestionReviewIn,
    TrackedOfferIn,
    TrackedOfferOut,
    UrlSuggestionAccepted,
    UrlSuggestionIn,
)

router = APIRouter(route_class=IdempotentRoute, tags=["sources"])


def _settings(body: SourceSettingsIn) -> registry.SourceSettings:
    return registry.SourceSettings(
        quota_per_minute=body.quota_per_minute,
        interval_a_seconds=body.interval_a_seconds,
        interval_b_seconds=body.interval_b_seconds,
        interval_c_seconds=body.interval_c_seconds,
    )


def _box(request: Request) -> SecretBox:
    return SecretBox.from_setting(request.app.state.settings.secret_encryption_keys)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(principal: ExpertPrincipal, db: DatabaseDep) -> list[SourceRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        return list((await session.scalars(select(SourceRow).order_by(SourceRow.name))).all())


@router.post("/sources", status_code=status.HTTP_201_CREATED, response_model=SourceOut)
async def create_source(body: SourceIn, principal: AdminPrincipal, db: DatabaseDep) -> SourceRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await registry.create_source(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            name=body.name,
            base_domain=body.base_domain,
            connector_key=body.connector_key,
            method=body.method,
            currency_unit=body.currency_unit,
            settings=_settings(body),
        )


@router.get("/sources/{source_id}", response_model=SourceDetailOut)
async def get_source(
    source_id: uuid.UUID, principal: AdminPrincipal, db: DatabaseDep
) -> SourceDetailOut:
    async with db.tenant_session(principal.tenant_id) as session:
        source = await registry.get_source(session, source_id)
        clearance = await registry.current_clearance(session, source_id)
        connector_config = await config.get_config(session, source_id)
        names = await config.secret_names(session, source_id)
    return SourceDetailOut.model_validate(
        {
            **SourceOut.model_validate(source).model_dump(),
            "clearance": ClearanceOut.model_validate(clearance) if clearance else None,
            "connector_config": connector_config,
            "secrets": dict.fromkeys(names, "set"),
        }
    )


@router.patch("/sources/{source_id}/settings", response_model=SourceOut)
async def update_settings(
    source_id: uuid.UUID, body: SourceSettingsIn, principal: AdminPrincipal, db: DatabaseDep
) -> SourceRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await registry.update_settings(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            settings=_settings(body),
        )


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: uuid.UUID, body: SourceUpdateIn, principal: AdminPrincipal, db: DatabaseDep
) -> SourceRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await registry.update_source(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            changes=registry.SourceChanges(
                name=body.name,
                base_domain=body.base_domain,
                connector_key=body.connector_key,
                method=body.method,
                currency_unit=body.currency_unit,
                settings=_settings(body.settings) if body.settings else None,
            ),
        )


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: uuid.UUID, body: SourceDeleteIn, principal: AdminPrincipal, db: DatabaseDep
) -> Response:
    async with db.tenant_session(principal.tenant_id) as session:
        await registry.delete_source(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            reason=body.reason,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sources/{source_id}/status", response_model=SourceOut)
async def change_status(
    source_id: uuid.UUID, body: StatusChangeIn, principal: AdminPrincipal, db: DatabaseDep
) -> SourceRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await registry.change_status(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            target=body.status,
            reason=body.reason,
        )


@router.get("/sources/{source_id}/clearances", response_model=list[ClearanceOut])
async def clearance_history(
    source_id: uuid.UUID, principal: AdminPrincipal, db: DatabaseDep
) -> list[SourceClearanceRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        rows = await session.scalars(
            select(SourceClearanceRow)
            .where(SourceClearanceRow.source_id == source_id)
            .order_by(SourceClearanceRow.created_at.desc())
        )
        return list(rows.all())


@router.post(
    "/sources/{source_id}/clearances",
    status_code=status.HTTP_201_CREATED,
    response_model=ClearanceOut,
)
async def grant_clearance(
    source_id: uuid.UUID, body: ClearanceIn, principal: AdminPrincipal, db: DatabaseDep
) -> SourceClearanceRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await registry.grant_clearance(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            approver_name=body.approver_name,
            approved_on=body.approved_on,
            scope=body.scope,
            reference=body.reference,
            permitted_requests_per_minute=body.permitted_requests_per_minute,
        )


@router.post("/sources/{source_id}/clearances/revoke", response_model=ClearanceOut)
async def revoke_clearance(
    source_id: uuid.UUID, body: RevokeIn, principal: AdminPrincipal, db: DatabaseDep
) -> SourceClearanceRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await registry.revoke_clearance(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            reason=body.reason,
        )


@router.put("/sources/{source_id}/connector-config", response_model=ConnectorConfigIn)
async def put_connector_config(
    source_id: uuid.UUID, body: ConnectorConfigIn, principal: AdminPrincipal, db: DatabaseDep
) -> ConnectorConfigIn:
    async with db.tenant_session(principal.tenant_id) as session:
        stored = await config.put_config(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            config=body.config,
        )
    return ConnectorConfigIn(config=stored)


@router.put("/sources/{source_id}/secrets/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def put_secret(
    source_id: uuid.UUID,
    name: str,
    body: SecretIn,
    request: Request,
    principal: AdminPrincipal,
    db: DatabaseDep,
) -> Response:
    async with db.tenant_session(principal.tenant_id) as session:
        await config.set_secret(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            box=_box(request),
            source_id=source_id,
            name=name,
            value=body.value,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/sources/{source_id}/secrets/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(
    source_id: uuid.UUID, name: str, principal: AdminPrincipal, db: DatabaseDep
) -> Response:
    async with db.tenant_session(principal.tenant_id) as session:
        await config.delete_secret(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            name=name,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/variants/{variant_id}/tracked-offers", response_model=list[TrackedOfferOut])
async def variant_offers(
    variant_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> list[TrackedOfferRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        return await offers.offers_for_variant(session, variant_id)


@router.post("/tracked-offers", status_code=status.HTTP_201_CREATED, response_model=TrackedOfferOut)
async def register_offer(
    body: TrackedOfferIn, principal: ExpertPrincipal, db: DatabaseDep
) -> TrackedOfferRow:
    if (body.is_own_store or body.is_own_channel) and not principal.has_role(Role.ADMIN):
        raise PermissionDenied("Only admins register own-store or own-channel listings")
    async with db.tenant_session(principal.tenant_id) as session:
        return await offers.register_offer(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=body.source_id,
            variant_id=body.variant_id,
            url=str(body.url),
            external_id=body.external_id,
            is_own_store=body.is_own_store,
            is_own_channel=body.is_own_channel,
        )


@router.post("/tracked-offers/{tracked_offer_id}/review", response_model=TrackedOfferOut)
async def review_suggestion(
    tracked_offer_id: uuid.UUID,
    body: SuggestionReviewIn,
    principal: ExpertPrincipal,
    db: DatabaseDep,
) -> TrackedOfferRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await offers.review_suggestion(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            tracked_offer_id=tracked_offer_id,
            confirm=body.decision == "confirm",
            reason=body.reason,
        )


@router.post("/tracked-offers/{tracked_offer_id}/pause", response_model=TrackedOfferOut)
async def pause_offer(
    tracked_offer_id: uuid.UUID, body: PauseIn, principal: AdminPrincipal, db: DatabaseDep
) -> TrackedOfferRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await offers.set_paused(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            tracked_offer_id=tracked_offer_id,
            paused=body.paused,
            reason=body.reason,
        )


@router.post(
    "/sources/{source_id}/samples", status_code=status.HTTP_201_CREATED, response_model=SampleOut
)
async def add_sample(
    source_id: uuid.UUID,
    principal: AdminPrincipal,
    db: DatabaseDep,
    url: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> extraction_rules.SourceSampleRow:
    html = await read_limited(file, extraction_rules.MAX_SAMPLE_BYTES)
    async with db.tenant_session(principal.tenant_id) as session:
        return await extraction_rules.add_sample(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            url=url,
            html=html,
        )


@router.get("/sources/{source_id}/extraction-rules", response_model=list[ExtractionRuleOut])
async def list_rules(
    source_id: uuid.UUID, principal: AdminPrincipal, db: DatabaseDep
) -> list[ExtractionRuleVersionRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        return await extraction_rules.rule_versions(session, source_id)


@router.post(
    "/sources/{source_id}/extraction-rules",
    status_code=status.HTTP_201_CREATED,
    response_model=ExtractionRuleOut,
)
async def propose_rule(
    source_id: uuid.UUID, body: ExtractionRuleIn, principal: AdminPrincipal, db: DatabaseDep
) -> ExtractionRuleVersionRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await extraction_rules.propose_rule(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            source_id=source_id,
            config=body.config,
            origin=RuleOrigin.ADMIN,
        )


@router.post(
    "/sources/{source_id}/extraction-rules/suggest",
    status_code=status.HTTP_201_CREATED,
    response_model=ExtractionRuleOut,
)
async def suggest_rule(
    source_id: uuid.UUID, principal: AdminPrincipal, db: DatabaseDep, llm: LLMDep
) -> ExtractionRuleVersionRow:
    """LLM-suggested selector rule from the stored samples, stored as ``proposed``."""
    return await suggestions.suggest_extraction_rule(
        db, llm, tenant_id=principal.tenant_id, actor=actor_of(principal), source_id=source_id
    )


@router.post(
    "/sources/{source_id}/offer-url-suggestions",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UrlSuggestionAccepted,
)
async def request_url_suggestions(
    source_id: uuid.UUID, body: UrlSuggestionIn, principal: ExpertPrincipal, db: DatabaseDep
) -> UrlSuggestionAccepted:
    """Queue an LLM search for the variant's offer pages on this source (results: suggestions)."""
    request_id = await suggestions.request_url_suggestions(
        db,
        tenant_id=principal.tenant_id,
        actor=actor_of(principal),
        source_id=source_id,
        variant_id=body.variant_id,
    )
    return UrlSuggestionAccepted(request_id=request_id)


@router.post("/extraction-rules/{rule_version_id}/review", response_model=ExtractionRuleOut)
async def review_rule(
    rule_version_id: uuid.UUID, body: RuleReviewIn, principal: AdminPrincipal, db: DatabaseDep
) -> ExtractionRuleVersionRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await extraction_rules.review_rule(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            rule_version_id=rule_version_id,
            approve=body.decision == "approve",
            reason=body.reason,
        )


@router.post(
    "/qualification-runs", status_code=status.HTTP_201_CREATED, response_model=QualificationRunOut
)
async def start_qualification(
    body: QualificationRunIn, principal: AdminPrincipal, db: DatabaseDep
) -> qualification.QualificationRunRow:
    async with db.tenant_session(principal.tenant_id) as session:
        variant_ids = body.variant_ids
        if not variant_ids:
            rows = await session.scalars(
                select(TrackedOfferRow.variant_id)
                .where(TrackedOfferRow.source_id.in_(body.source_ids))
                .distinct()
                .limit(body.sample_size)
            )
            variant_ids = list(rows.all())
        return await qualification.start_run(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            variant_ids=variant_ids,
            source_ids=body.source_ids,
        )


@router.get("/qualification-runs/{run_id}", response_model=QualificationRunOut)
async def qualification_report(
    run_id: uuid.UUID, principal: AdminPrincipal, db: DatabaseDep
) -> qualification.QualificationRunRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await qualification.report(session, run_id)


@router.post("/qualification-runs/{run_id}/sources/{source_id}/decision", response_model=SourceOut)
async def qualification_decision(
    run_id: uuid.UUID,
    source_id: uuid.UUID,
    body: QualificationDecisionIn,
    principal: AdminPrincipal,
    db: DatabaseDep,
) -> SourceRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await qualification.decide_source(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            run_id=run_id,
            source_id=source_id,
            approve=body.decision == "approve",
            reason=body.reason,
        )
