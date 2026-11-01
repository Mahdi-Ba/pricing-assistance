"""Test-wide configuration. Integration tests use the separate ``pricing_test`` database."""

import os

_TEST_DB = "localhost:55432/pricing_test"
os.environ.setdefault("PA_ENVIRONMENT", "test")
os.environ.setdefault("PA_DATABASE_APP_URL", f"postgresql+asyncpg://pa_app:pa_app_dev@{_TEST_DB}")
os.environ.setdefault(
    "PA_DATABASE_OWNER_URL", f"postgresql+psycopg://pa_owner:pa_owner_dev@{_TEST_DB}"
)
os.environ.setdefault(
    "PA_DATABASE_MAINTENANCE_URL",
    f"postgresql+asyncpg://pa_maintenance:pa_maintenance_dev@{_TEST_DB}",
)
os.environ.setdefault("PA_REDIS_URL", "redis://localhost:56390/15")
os.environ.setdefault("PA_S3_BUCKET", "pricing-evidence-test")
