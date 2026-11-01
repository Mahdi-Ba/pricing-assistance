import pytest

from pricing_assistant.audit.api import list_events
from pricing_assistant.core.db import Database
from tests.support.api import api_client, auth

from .conftest import TENANT_A, TENANT_B

pytestmark = pytest.mark.integration


async def test_admin_changes_recheck_budget_and_change_is_audited(db: Database) -> None:
    async with api_client(db) as client:
        defaults = await client.get("/settings", headers=auth(TENANT_A, "expert"))
        updated = await client.patch(
            "/settings", headers=auth(TENANT_A, "admin"), json={"recheck_daily_budget_per_user": 80}
        )
        other_tenant = await client.get("/settings", headers=auth(TENANT_B, "expert"))
        denied = await client.patch(
            "/settings", headers=auth(TENANT_A, "expert"), json={"recheck_daily_budget_per_user": 1}
        )
        invalid = await client.patch(
            "/settings", headers=auth(TENANT_A, "admin"), json={"unknown_key": 1}
        )
    assert defaults.json()["recheck_daily_budget_per_user"] == 50
    assert updated.json()["recheck_daily_budget_per_user"] == 80
    assert updated.json()["verification_window_minutes"] == 120
    assert other_tenant.json()["recheck_daily_budget_per_user"] == 50
    assert denied.status_code == 403
    assert invalid.status_code == 422
    async with db.tenant_session(TENANT_A) as session:
        [event] = await list_events(session, action="tenant.settings.changed")
    assert event.before is not None
    assert event.after is not None
    assert (
        event.before["recheck_daily_budget_per_user"],
        event.after["recheck_daily_budget_per_user"],
    ) == (50, 80)
