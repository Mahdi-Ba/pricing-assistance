import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.matching.models import MatchVersionRow
from tests.support.seed import seed_offer, seed_source, seed_variant

from .conftest import TENANT_A

pytestmark = pytest.mark.integration


def _version(offer: uuid.UUID, variant: uuid.UUID, **overrides: object) -> MatchVersionRow:
    values: dict[str, object] = {
        "id": new_id(),
        "tenant_id": TENANT_A,
        "tracked_offer_id": offer,
        "seller_key": "",
        "variant_id": variant,
        "state": "proposed",
        "flags": [],
        "confidence_bp": 9000,
        "decided_by": "rule",
        "actor": "system",
        "attributes_hash": "h",
        "is_current": True,
    }
    values.update(overrides)
    return MatchVersionRow(**values)


async def _ids(db: Database) -> tuple[uuid.UUID, uuid.UUID]:
    variant = await seed_variant(db, TENANT_A)
    source = await seed_source(db, TENANT_A)
    return await seed_offer(db, TENANT_A, source_id=source, variant_id=variant), variant


async def test_only_one_current_match_per_market_offer(db: Database) -> None:
    offer, variant = await _ids(db)
    with pytest.raises(IntegrityError, match="uq_match_version_current"):
        async with db.tenant_session(TENANT_A) as session:
            session.add(_version(offer, variant))
            await session.flush()
            session.add(_version(offer, variant))
            await session.flush()


async def test_llm_can_never_confirm(db: Database) -> None:
    offer, variant = await _ids(db)
    with pytest.raises(IntegrityError, match="llm_never_confirms"):
        async with db.tenant_session(TENANT_A) as session:
            session.add(_version(offer, variant, state="confirmed", decided_by="llm"))


async def test_match_values_are_immutable(db: Database) -> None:
    offer, variant = await _ids(db)
    async with db.tenant_session(TENANT_A) as session:
        session.add(_version(offer, variant))
    async with db.tenant_session(TENANT_A) as session:
        await session.execute(text("UPDATE match_version SET is_current = false"))
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db.tenant_session(TENANT_A) as session:
            await session.execute(text("UPDATE match_version SET state = 'confirmed'"))
