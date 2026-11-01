"""Admin HTTP API for catalog imports, cost components, cost review and profit rules."""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from sqlalchemy import select

from pricing_assistant.catalog import costs, rules
from pricing_assistant.catalog.importing import run_import
from pricing_assistant.catalog.models import CatalogImportRow, CostRecordRow, CostRecordState
from pricing_assistant.catalog.queries import list_variants
from pricing_assistant.catalog.schemas import (
    CostComponentIn,
    CostComponentOut,
    CostRecordOut,
    CostReviewIn,
    ImportReportOut,
    ReasonIn,
    ResolvedRuleOut,
    RuleValuesIn,
    RuleVersionIn,
    RuleVersionOut,
    VariantSummaryOut,
)
from pricing_assistant.catalog.template import TEMPLATE_COLUMNS
from pricing_assistant.catalog.upload import Upload, detect_format
from pricing_assistant.core.deps import DatabaseDep, SettingsDep
from pricing_assistant.core.errors import NotFound, PayloadTooLarge, ValidationFailed
from pricing_assistant.core.idempotency import IdempotentRoute
from pricing_assistant.core.money import CurrencyUnit, MoneyParseError, parse_currency_unit
from pricing_assistant.core.uploads import read_limited
from pricing_assistant.iam.api import AdminPrincipal, ExpertPrincipal, actor_of

router = APIRouter(route_class=IdempotentRoute)
_MULTIPART_OVERHEAD = 64 * 1024


@router.get("/catalog/import-template", tags=["catalog"], response_class=Response)
async def import_template(_principal: AdminPrincipal) -> Response:
    buffer = io.StringIO()
    csv.writer(buffer).writerow(TEMPLATE_COLUMNS)
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="catalog-template.csv"'},
    )


@router.post(
    "/catalog/imports",
    tags=["catalog"],
    status_code=status.HTTP_201_CREATED,
    response_model=ImportReportOut,
)
async def create_import(
    request: Request,
    principal: AdminPrincipal,
    db: DatabaseDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    default_currency: Annotated[str | None, Form()] = None,
) -> CatalogImportRow:
    declared = request.headers.get("content-length")
    if declared and int(declared) > settings.catalog_max_upload_bytes + _MULTIPART_OVERHEAD:
        raise PayloadTooLarge("Upload exceeds the size limit")
    data = await read_limited(file, settings.catalog_max_upload_bytes)
    name = file.filename or "upload"
    file_format = detect_format(
        name, data, max_uncompressed_bytes=settings.catalog_max_uncompressed_bytes
    )
    try:
        unit: CurrencyUnit | None = parse_currency_unit(default_currency)
    except MoneyParseError as exc:
        raise ValidationFailed(
            "default_currency must be RIAL or TOMAN", message_fa="واحد پول باید ریال یا تومان باشد."
        ) from exc
    async with db.tenant_session(principal.tenant_id) as session:
        return await run_import(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            upload=Upload(file_name=name, file_format=file_format, data=data),
            default_currency=unit,
            max_rows=settings.catalog_max_rows,
        )


@router.get("/catalog/imports", tags=["catalog"], response_model=list[ImportReportOut])
async def list_imports(principal: AdminPrincipal, db: DatabaseDep) -> list[CatalogImportRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        rows = await session.scalars(
            select(CatalogImportRow).order_by(CatalogImportRow.created_at.desc()).limit(50)
        )
        return list(rows.all())


@router.get("/catalog/imports/{import_id}", tags=["catalog"], response_model=ImportReportOut)
async def get_import(
    import_id: uuid.UUID, principal: AdminPrincipal, db: DatabaseDep
) -> CatalogImportRow:
    async with db.tenant_session(principal.tenant_id) as session:
        row = await session.get(CatalogImportRow, import_id)
    if row is None:
        raise NotFound("Import not found", message_fa="گزارش بارگذاری یافت نشد.")
    return row


@router.get("/catalog/cost-components", tags=["catalog"], response_model=list[CostComponentOut])
async def list_components(
    principal: AdminPrincipal, db: DatabaseDep
) -> list[costs.CostComponentRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        return await costs.active_components(session)


@router.post(
    "/catalog/cost-components",
    tags=["catalog"],
    status_code=status.HTTP_201_CREATED,
    response_model=CostComponentOut,
)
async def add_component(
    body: CostComponentIn, principal: AdminPrincipal, db: DatabaseDep
) -> costs.CostComponentRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await costs.add_component(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            name=body.name,
            amount_rial=body.amount_rial,
            category=body.category,
        )


@router.post(
    "/catalog/cost-components/{component_id}/deactivate",
    tags=["catalog"],
    response_model=CostComponentOut,
)
async def deactivate_component(
    component_id: uuid.UUID, body: ReasonIn, principal: AdminPrincipal, db: DatabaseDep
) -> costs.CostComponentRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await costs.deactivate_component(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            component_id=component_id,
            reason=body.reason,
        )


@router.get("/catalog/held-costs", tags=["catalog"], response_model=list[CostRecordOut])
async def held_costs(
    principal: AdminPrincipal, db: DatabaseDep, import_id: uuid.UUID | None = None
) -> list[CostRecordRow]:
    """Cost versions held as ``suspect_unit`` and waiting for an admin (optionally per import)."""
    query = select(CostRecordRow).where(CostRecordRow.state == CostRecordState.HELD.value)
    if import_id is not None:
        query = query.where(CostRecordRow.import_id == import_id)
    async with db.tenant_session(principal.tenant_id) as session:
        return list((await session.scalars(query.order_by(CostRecordRow.created_at))).all())


@router.get("/catalog/variants", tags=["catalog"], response_model=list[VariantSummaryOut])
async def list_catalog_variants(
    principal: ExpertPrincipal,
    db: DatabaseDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[VariantSummaryOut]:
    """Variants matching ``q`` (SKU, name, brand or model), e.g. to pick a re-assign target."""
    needle = (q or "").strip().casefold()
    async with db.tenant_session(principal.tenant_id) as session:
        variants = await list_variants(session)
    found = [
        v
        for v in variants
        if not needle or needle in f"{v.sku} {v.product_name} {v.brand} {v.model}".casefold()
    ]
    return [
        VariantSummaryOut(
            id=v.id,
            sku=v.sku,
            product_name=v.product_name,
            category=v.category,
            brand=v.brand,
            model=v.model,
            importance_tier=v.importance_tier.value,
            attributes=v.attributes,
        )
        for v in found[:limit]
    ]


@router.get(
    "/catalog/variants/{variant_id}/costs", tags=["catalog"], response_model=list[CostRecordOut]
)
async def variant_costs(
    variant_id: uuid.UUID, principal: AdminPrincipal, db: DatabaseDep
) -> list[CostRecordRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        return await costs.cost_history(session, variant_id)


@router.post(
    "/catalog/costs/{cost_record_id}/review", tags=["catalog"], response_model=CostRecordOut
)
async def review_cost(
    cost_record_id: uuid.UUID, body: CostReviewIn, principal: AdminPrincipal, db: DatabaseDep
) -> CostRecordRow:
    async with db.tenant_session(principal.tenant_id) as session:
        return await costs.review_held_cost(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            cost_record_id=cost_record_id,
            confirm=body.decision == "confirm",
            reason=body.reason,
        )


@router.get("/rules/suggested-defaults", tags=["rules"], response_model=RuleValuesIn)
async def suggested_defaults(_principal: AdminPrincipal) -> RuleValuesIn:
    return RuleValuesIn(**rules.SUGGESTED_DEFAULTS.as_dict())


@router.get("/rules", tags=["rules"], response_model=list[RuleVersionOut])
async def current_rules(
    principal: ExpertPrincipal, db: DatabaseDep
) -> list[rules.ProfitRuleVersionRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        return await rules.current_versions(session)


@router.get("/rules/history", tags=["rules"], response_model=list[RuleVersionOut])
async def rule_history(
    principal: ExpertPrincipal,
    db: DatabaseDep,
    scope: rules.RuleScope,
    key: str | None = None,
) -> list[rules.ProfitRuleVersionRow]:
    async with db.tenant_session(principal.tenant_id) as session:
        return await rules.history(session, scope, key)


@router.get("/rules/resolved/{variant_id}", tags=["rules"], response_model=ResolvedRuleOut)
async def resolved_rule(
    variant_id: uuid.UUID, principal: ExpertPrincipal, db: DatabaseDep
) -> ResolvedRuleOut:
    async with db.tenant_session(principal.tenant_id) as session:
        resolved = await rules.resolve_for_variant(session, variant_id)
    if resolved is None:
        raise NotFound(
            "No complete default rule is defined",
            code="rule_missing",
            message_fa="قاعده سود پیش‌فرض (به‌همراه نرخ مالیات) تعریف نشده است.",
        )
    return ResolvedRuleOut(
        variant_id=variant_id,
        min_margin_bp=resolved.min_margin_bp,
        fee_rate_bp=resolved.fee_rate_bp,
        vat_rate_bp=resolved.vat_rate_bp,
        ceiling_rial=resolved.ceiling_rial,
        undercut_step_rial=resolved.undercut_step_rial,
        hold_tolerance_bp=resolved.hold_tolerance_bp,
        rounding_step_rial=resolved.rounding_step_rial,
        max_data_age_seconds={k.value: v for k, v in resolved.max_data_age_seconds.items()},
        outlier_threshold_bp=resolved.outlier_threshold_bp,
        min_qualifying_offers=resolved.min_qualifying_offers,
        competitor_set=resolved.competitor_set,
        version_ids=list(resolved.version_ids),
    )


async def _put_rule(
    principal: AdminPrincipal,
    db: DatabaseDep,
    scope: rules.RuleScope,
    key: str | None,
    body: RuleVersionIn,
) -> rules.ProfitRuleVersionRow:
    values = RuleValuesIn.model_validate(body.model_dump(exclude={"reason"}))
    async with db.tenant_session(principal.tenant_id) as session:
        return await rules.create_version(
            session,
            tenant_id=principal.tenant_id,
            actor=actor_of(principal),
            scope=scope,
            scope_key=key,
            values=values.to_fields(),
            reason=body.reason,
        )


@router.put(
    "/rules/default",
    tags=["rules"],
    status_code=status.HTTP_201_CREATED,
    response_model=RuleVersionOut,
)
async def put_default_rule(
    body: RuleVersionIn, principal: AdminPrincipal, db: DatabaseDep
) -> rules.ProfitRuleVersionRow:
    return await _put_rule(principal, db, rules.RuleScope.DEFAULT, None, body)


@router.put(
    "/rules/category/{category}",
    tags=["rules"],
    status_code=status.HTTP_201_CREATED,
    response_model=RuleVersionOut,
)
async def put_category_rule(
    category: str, body: RuleVersionIn, principal: AdminPrincipal, db: DatabaseDep
) -> rules.ProfitRuleVersionRow:
    return await _put_rule(principal, db, rules.RuleScope.CATEGORY, category.lower(), body)


@router.put(
    "/rules/variant/{variant_id}",
    tags=["rules"],
    status_code=status.HTTP_201_CREATED,
    response_model=RuleVersionOut,
)
async def put_variant_rule(
    variant_id: uuid.UUID, body: RuleVersionIn, principal: AdminPrincipal, db: DatabaseDep
) -> rules.ProfitRuleVersionRow:
    return await _put_rule(principal, db, rules.RuleScope.VARIANT, str(variant_id), body)
