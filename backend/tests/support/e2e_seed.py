"""Seed data for the browser end-to-end tests (web/tests/e2e).

Uses its own database (``pricing_e2e``) and Redis DB 14, so it never touches development data or
the integration-test database. Data is created through the domain services (matching, pricing,
decisions), not by hand-written rows, so the UI sees what the real pipeline produces.

    uv run python -m tests.support.e2e_seed reset          # migrate, wipe and seed
    uv run python -m tests.support.e2e_seed supersede SKU  # new recommendation version (stale test)
"""

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

E2E_DB = "localhost:55432/pricing_e2e"
E2E_ENV = {
    "PA_ENVIRONMENT": "dev",
    "PA_DATABASE_APP_URL": f"postgresql+asyncpg://pa_app:pa_app_dev@{E2E_DB}",
    "PA_DATABASE_OWNER_URL": f"postgresql+psycopg://pa_owner:pa_owner_dev@{E2E_DB}",
    "PA_DATABASE_MAINTENANCE_URL": f"postgresql+asyncpg://pa_maintenance:pa_maintenance_dev@{E2E_DB}",
    "PA_REDIS_URL": "redis://localhost:56390/14",
    "PA_S3_BUCKET": "pricing-evidence-e2e",
}
for _key, _value in E2E_ENV.items():
    os.environ.setdefault(_key, _value)

# ruff: noqa: E402 - the environment must be set before settings are imported
import psycopg
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from pricing_assistant.catalog.models import VariantRow
from pricing_assistant.collection.models import FetchAttemptRow, ObservationRow
from pricing_assistant.core.db import Database
from pricing_assistant.core.db import create_engine as create_async_engine
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.settings import get_settings
from pricing_assistant.matching.extract import seller_key
from pricing_assistant.matching.service import (
    ExpertAction,
    MarketOffer,
    decide,
    evaluate,
    record_attributes,
)
from pricing_assistant.pricing.service import recompute
from pricing_assistant.sources.models import RuleOrigin, SourceStatus
from pricing_assistant.sources.offers import suggest_offer
from pricing_assistant.sources.rules import add_sample, propose_rule
from tests.support.fixtures import FIXTURES, fixture_json
from tests.support.pricing import default_rule
from tests.support.seed import ADMIN, seed_cost, seed_offer, seed_source, seed_variant

TENANT_A = uuid.UUID("0192f0a0-0000-7000-8000-000000000001")
TENANT_B = uuid.UUID("0192f0a0-0000-7000-8000-000000000002")
BACKEND = Path(__file__).resolve().parents[2]
# The demo stack must never contact a real shop: its clearances are test fixtures, not real
# permissions. ".test" is reserved (RFC 6761) and never resolves, so even a worker started with the
# collect queue cannot reach a real site from this data.
DEMO_DOMAIN = "shop.pricing-demo.test"
SITE = f"https://{DEMO_DOMAIN}"
WARRANTY = {"warranty": "گارانتی ۳۶ ماهه آواژنگ"}


def ensure_database() -> None:
    admin_url = "postgresql://pa_owner:pa_owner_dev@localhost:55432/postgres"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = 'pricing_e2e'").fetchone()
        if not exists:
            conn.execute("CREATE DATABASE pricing_e2e OWNER pa_owner")
        conn.execute("GRANT CONNECT ON DATABASE pricing_e2e TO pa_app, pa_maintenance")


def migrate_and_wipe() -> None:
    owner_url = get_settings().database_owner_url.get_secret_value()
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["url"] = owner_url
    command.upgrade(config, "head")
    engine = create_engine(owner_url, poolclass=NullPool)
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        ).scalars()
        conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
        for tenant, name in ((TENANT_A, "Pilot store"), (TENANT_B, "Sandbox store")):
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
            conn.execute(
                text("INSERT INTO tenant (id, name) VALUES (:id, :name)"),
                {"id": tenant, "name": name},
            )
    engine.dispose()


async def observe(
    db: Database,
    offer: uuid.UUID,
    source: uuid.UUID,
    variant: uuid.UUID,
    *,
    price: int,
    title: str,
    seller: str,
    conditions: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> ObservationRow:
    at = at or datetime.now(UTC) - timedelta(minutes=8)
    async with db.tenant_session(TENANT_A) as session:
        attempt = FetchAttemptRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=source,
            window_start=at,
            attempt=1,
            trigger="scheduled",
            outcome="success",
            offers_count=1,
            final=True,
            correlation_id="e2e-seed",
            finished_at=at,
        )
        session.add(attempt)
        await session.flush()
        observation = ObservationRow(
            id=new_id(),
            tenant_id=TENANT_A,
            tracked_offer_id=offer,
            source_id=source,
            variant_id=variant,
            fetch_attempt_id=attempt.id,
            observed_at=at,
            url=f"{SITE}/p/{offer.hex[:8]}",
            method="html",
            seller=seller,
            title=title,
            price_rial=price,
            stock_state="in_stock",
            conditions=conditions if conditions is not None else WARRANTY,
            identifiers={},
            validity="valid",
            is_own_store=False,
            is_own_channel=False,
            evidence_ids=[],
        )
        session.add(observation)
    return observation


async def matched_offer(
    db: Database,
    variant: uuid.UUID,
    *,
    source_name: str,
    seller: str,
    price: int,
    title: str,
    confirm: bool = True,
) -> uuid.UUID:
    source = await seed_source(db, TENANT_A, base_domain=DEMO_DOMAIN, name=source_name, quota=60)
    offer = await seed_offer(
        db,
        TENANT_A,
        source_id=source,
        variant_id=variant,
        url=f"{SITE}/{source_name.lower()}/{variant.hex[:8]}",
    )
    observation = await observe(db, offer, source, variant, price=price, title=title, seller=seller)
    async with db.tenant_session(TENANT_A) as session:
        await record_attributes(session, TENANT_A, observation)
        version = await evaluate(session, TENANT_A, MarketOffer(offer, seller_key(seller)))
    if confirm and version is not None and version.state != "confirmed":
        async with db.tenant_session(TENANT_A) as session:
            await decide(
                session,
                tenant_id=TENANT_A,
                actor=ADMIN,
                match_version_id=version.id,
                action=ExpertAction.CONFIRM,
                reason="e2e seed",
            )
    return offer


async def recompute_all(db: Database, variants: list[uuid.UUID]) -> None:
    for variant in variants:
        async with db.tenant_session(TENANT_A) as session:
            await recompute(session, TENANT_A, variant)


async def seed(db: Database) -> None:
    await default_rule(db, TENANT_A, rounding_step_rial=100_000)
    ssd = await seed_variant(db, TENANT_A, sku="SSD-990-1TB", tier="A", price_rial=89_000_000)
    await seed_cost(db, TENANT_A, ssd, 75_600_000)  # floor 84,000,000
    title = "SSD سامسونگ 990 PRO 1TB"
    await matched_offer(db, ssd, source_name="Lion", seller="لیون", price=86_000_000, title=title)
    await matched_offer(
        db, ssd, source_name="Meghdad", seller="مقداد", price=87_000_000, title=title
    )
    await matched_offer(
        db, ssd, source_name="Cheapo", seller="ارزان", price=60_000_000, title=title
    )
    # a page that is the 2TB model: needs review, shown in /matches with a capacity diff
    await matched_offer(
        db,
        ssd,
        source_name="Wrong",
        seller="فروشگاه دیگر",
        price=88_000_000,
        title="SSD سامسونگ 990 PRO 2TB",
        confirm=False,
    )

    ram = await seed_variant(
        db,
        TENANT_A,
        sku="RAM-K5600",
        category="ram",
        tier="B",
        price_rial=90_000_000,
        brand="Kingston",
        model="DDR5",
        attributes={
            "capacity": "32GB",
            "frequency": "5600",
            "warranty_provider": "آواژنگ",
            "warranty_months": 36,
        },
    )
    await seed_cost(db, TENANT_A, ram, 75_000_000)
    await matched_offer(
        db,
        ram,
        source_name="RamShop",
        seller="رم‌شاپ",
        price=95_000_000,
        title="رم کینگستون DDR5 32GB 5600MHz",
    )

    gpu = await seed_variant(
        db,
        TENANT_A,
        sku="GPU-4060",
        category="gpu",
        tier="A",
        price_rial=150_000_000,
        brand="ASUS",
        model="RTX 4060",
        attributes={"capacity": "8GB", "warranty_provider": "آواژنگ", "warranty_months": 36},
    )
    await seed_cost(db, TENANT_A, gpu, 140_000_000)  # floor above the market: floor conflict
    await matched_offer(
        db,
        gpu,
        source_name="GpuShop",
        seller="جی‌پی‌یو",
        price=145_000_000,
        title="کارت گرافیک ایسوس RTX 4060 8GB",
    )

    hold = await seed_variant(
        db,
        TENANT_A,
        sku="SSD-870-500",
        tier="C",
        price_rial=40_000_000,
        model="870 EVO",
        attributes={"capacity": "500GB", "warranty_provider": "آواژنگ", "warranty_months": 36},
    )
    await seed_cost(db, TENANT_A, hold, 30_000_000)
    await matched_offer(
        db,
        hold,
        source_name="EvoShop",
        seller="اوو",
        price=40_000_000,
        title="SSD سامسونگ 870 EVO 500GB",
    )
    await recompute_all(db, [ssd, ram, gpu, hold])

    # a suggested competitor URL waiting for confirmation
    lion = await seed_source(
        db, TENANT_A, base_domain=DEMO_DOMAIN, name="Lion Suggestions", quota=60
    )
    async with db.tenant_session(TENANT_A) as session:
        await suggest_offer(
            session,
            tenant_id=TENANT_A,
            suggested_by="llm",
            source_id=lion,
            variant_id=ram,
            url=f"{SITE}/product/kingston-ddr5-32gb-5600",
            rationale="همان مدل، ظرفیت و فرکانس",
        )

    # admin scenarios: a candidate source without clearance, and a proposed extraction rule
    await seed_source(
        db,
        TENANT_A,
        base_domain=DEMO_DOMAIN,
        name="Candidate Shop",
        status=SourceStatus.CANDIDATE,
        cleared=False,
        quota=10,
    )
    rule_source = await seed_source(
        db, TENANT_A, base_domain=DEMO_DOMAIN, name="Rule Shop", quota=10
    )
    async with db.tenant_session(TENANT_A) as session:
        await add_sample(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=rule_source,
            url=f"{SITE}/p/sellers",
            html=(FIXTURES / "generic/marketplace_sellers.html").read_bytes(),
        )
        await propose_rule(
            session,
            tenant_id=TENANT_A,
            actor=ADMIN,
            source_id=rule_source,
            config=fixture_json("generic/marketplace_rule.json"),
            origin=RuleOrigin.ADMIN,
        )


async def supersede(db: Database, sku: str) -> None:
    """A new cost makes a new recommendation version, as a new observation would."""
    async with db.tenant_session(TENANT_A) as session:
        variant = await session.scalar(select(VariantRow.id).where(VariantRow.sku == sku))
    if variant is None:
        raise SystemExit(f"unknown sku {sku}")
    await seed_cost(db, TENANT_A, variant, 75_000_000)
    async with db.tenant_session(TENANT_A) as session:
        row = await recompute(session, TENANT_A, variant)
    if row is None:
        raise SystemExit("the recommendation did not change")


async def main(args: list[str]) -> None:
    settings = get_settings()
    db = Database(create_async_engine(settings.database_app_url, pool_size=2))
    try:
        if args[:1] == ["reset"]:
            redis = Redis.from_url(settings.redis_url.get_secret_value())
            await redis.flushdb()
            await redis.aclose()
            await seed(db)
        elif args[:1] == ["supersede"] and len(args) == 2:
            await supersede(db, args[1])
        else:
            raise SystemExit(__doc__)
    finally:
        await db.dispose()


if __name__ == "__main__":
    if sys.argv[1:2] == ["reset"]:
        ensure_database()
        migrate_and_wipe()
    asyncio.run(main(sys.argv[1:]))
    print("e2e seed: ok")
