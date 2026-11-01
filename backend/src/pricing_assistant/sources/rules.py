"""Versioned extraction rules and their approval workflow (task 4.12).

A new selector rule — written by an admin or suggested by the language model — is stored as
``proposed`` together with its results on the source's stored sample pages. It becomes the
single ``active`` version only when an admin approves it, and only if it extracted at least one
offer from every sample. Live extraction keeps using the current active version until then.
"""

import gzip
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.audit.api import AuditActor, record
from pricing_assistant.core.db import Base
from pricing_assistant.core.errors import Conflict, NotFound, ValidationFailed
from pricing_assistant.core.events import publish
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.money import CurrencyUnit
from pricing_assistant.sources.events import ExtractionRuleActivated
from pricing_assistant.sources.extraction import ExtractionError, extract_with_rule, parse_rule
from pricing_assistant.sources.http_fetcher import host_allowed
from pricing_assistant.sources.models import ExtractionRuleVersionRow, RuleOrigin, RuleVersionState
from pricing_assistant.sources.registry import get_source

MAX_SAMPLE_BYTES = 5 * 1024 * 1024


class SourceSampleRow(Base):
    __tablename__ = "source_sample"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source.id"))
    url: Mapped[str] = mapped_column(Text)
    html_gzip: Mapped[bytes] = mapped_column(LargeBinary)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def html(self) -> str:
        return gzip.decompress(self.html_gzip).decode("utf-8", errors="replace")


async def add_sample(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    url: str,
    html: bytes,
) -> SourceSampleRow:
    source = await get_source(session, source_id)
    if not host_allowed(url, source.base_domain):
        raise ValidationFailed(f"Sample URL must be on {source.base_domain}")
    if not html or len(html) > MAX_SAMPLE_BYTES:
        raise ValidationFailed("Sample page must be between 1 byte and 5 MB")
    sample = SourceSampleRow(
        id=new_id(),
        tenant_id=tenant_id,
        source_id=source_id,
        url=url,
        html_gzip=gzip.compress(html, mtime=0),
        created_by=actor.username,
    )
    session.add(sample)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.sample.added",
        target_type="source",
        target_id=source_id,
        after={"sample_id": str(sample.id), "url": url, "bytes": len(html)},
    )
    return sample


async def samples(session: AsyncSession, source_id: uuid.UUID) -> list[SourceSampleRow]:
    rows = await session.scalars(
        select(SourceSampleRow)
        .where(SourceSampleRow.source_id == source_id)
        .order_by(SourceSampleRow.created_at)
    )
    return list(rows.all())


def validate_on_samples(
    config: dict[str, Any], pages: list[SourceSampleRow], unit: CurrencyUnit
) -> dict[str, Any]:
    """Run the rule on every sample; pass only if each yields at least one offer."""
    rule = parse_rule(config)
    results: list[dict[str, Any]] = []
    for sample in pages:
        try:
            extraction = extract_with_rule(sample.html(), rule, unit)
        except ExtractionError as exc:
            results.append({"sample_id": str(sample.id), "url": sample.url, "error": str(exc)})
            continue
        results.append(
            {
                "sample_id": str(sample.id),
                "url": sample.url,
                "offers": len(extraction.offers),
                "prices_rial": [o.price_rial for o in extraction.offers],
                "stock": [o.stock.value for o in extraction.offers],
                "sellers": [o.seller for o in extraction.offers],
            }
        )
    passed = bool(results) and all("error" not in r and r["offers"] > 0 for r in results)
    return {"passed": passed, "sample_count": len(results), "results": results}


async def propose_rule(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    source_id: uuid.UUID,
    config: dict[str, Any],
    origin: RuleOrigin,
) -> ExtractionRuleVersionRow:
    source = await get_source(session, source_id)
    try:
        validation = validate_on_samples(
            config, await samples(session, source_id), CurrencyUnit(source.currency_unit)
        )
    except ValueError as exc:
        raise ValidationFailed(str(exc), code="invalid_extraction_rule") from exc
    latest = await session.scalar(
        select(func.max(ExtractionRuleVersionRow.version)).where(
            ExtractionRuleVersionRow.source_id == source_id
        )
    )
    version = ExtractionRuleVersionRow(
        id=new_id(),
        tenant_id=tenant_id,
        source_id=source_id,
        version=(latest or 0) + 1,
        config=config,
        state=RuleVersionState.PROPOSED.value,
        origin=origin.value,
        validation=validation,
        created_by=actor.username,
    )
    session.add(version)
    await session.flush()
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.extraction_rule.proposed",
        target_type="extraction_rule_version",
        target_id=version.id,
        after={"version": version.version, "origin": origin.value, "passed": validation["passed"]},
    )
    return version


async def review_rule(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: AuditActor,
    rule_version_id: uuid.UUID,
    approve: bool,
    reason: str,
) -> ExtractionRuleVersionRow:
    if not reason.strip():
        raise ValidationFailed("A reason is required", message_fa="دلیل را وارد کنید.")
    version = await session.get(ExtractionRuleVersionRow, rule_version_id, with_for_update=True)
    if version is None:
        raise NotFound("Extraction rule version not found")
    if version.state != RuleVersionState.PROPOSED.value:
        raise Conflict("Only proposed rule versions can be reviewed")
    if approve and not (version.validation or {}).get("passed"):
        raise Conflict(
            "The rule did not extract offers from every sample page",
            code="rule_validation_failed",
            message_fa="این قاعده روی همه صفحه‌های نمونه پیشنهاد قیمت استخراج نکرد.",
        )
    now = datetime.now(UTC)
    if approve:
        current = await session.scalar(
            select(ExtractionRuleVersionRow)
            .where(
                ExtractionRuleVersionRow.source_id == version.source_id,
                ExtractionRuleVersionRow.state == RuleVersionState.ACTIVE.value,
            )
            .with_for_update()
        )
        if current is not None:
            current.state = RuleVersionState.RETIRED.value
            await session.flush()
    version.state = (RuleVersionState.ACTIVE if approve else RuleVersionState.REJECTED).value
    version.reviewed_by = actor.username
    version.reviewed_at = now
    version.review_reason = reason
    await session.flush()
    if approve:
        await publish(
            session,
            tenant_id=tenant_id,
            event=ExtractionRuleActivated(source_id=version.source_id, rule_version_id=version.id),
        )
    await record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="source.extraction_rule.approved" if approve else "source.extraction_rule.rejected",
        target_type="extraction_rule_version",
        target_id=version.id,
        before={"state": RuleVersionState.PROPOSED.value},
        after={"state": version.state, "origin": version.origin},
        reason=reason,
    )
    return version


async def rule_versions(
    session: AsyncSession, source_id: uuid.UUID
) -> list[ExtractionRuleVersionRow]:
    rows = await session.scalars(
        select(ExtractionRuleVersionRow)
        .where(ExtractionRuleVersionRow.source_id == source_id)
        .order_by(ExtractionRuleVersionRow.version.desc())
    )
    return list(rows.all())
