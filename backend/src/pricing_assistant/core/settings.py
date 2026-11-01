"""Typed application settings.

Values come from environment variables prefixed with ``PA_`` and, for secrets, optionally from
files in ``PA_SECRETS_DIR`` (one file per field, e.g. a mounted Kubernetes Secret). Secret
fields are ``SecretStr`` so they never appear in ``repr``, logs or error messages.
"""

import os
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PA_",
        env_file=None,
        extra="ignore",
        frozen=True,
        secrets_dir=os.environ.get("PA_SECRETS_DIR") or None,
    )

    environment: Environment = Environment.DEV
    service_name: str = "pricing-assistant"
    log_level: str = "INFO"
    log_json: bool = True

    # Database: three least-privilege roles (design D4).
    database_app_url: SecretStr = SecretStr(
        "postgresql+asyncpg://pa_app:pa_app_dev@localhost:55432/pricing"
    )
    database_owner_url: SecretStr = SecretStr(
        "postgresql+psycopg://pa_owner:pa_owner_dev@localhost:55432/pricing"
    )
    database_maintenance_url: SecretStr = SecretStr(
        "postgresql+asyncpg://pa_maintenance:pa_maintenance_dev@localhost:55432/pricing"
    )
    database_app_role: str = "pa_app"
    database_maintenance_role: str = "pa_maintenance"
    database_pool_size: Annotated[int, Field(ge=1, le=100)] = 10

    redis_url: SecretStr = SecretStr("redis://localhost:56390/0")

    s3_endpoint_url: str | None = "http://localhost:59000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "pricing-evidence"
    s3_access_key: SecretStr = SecretStr("pa_minio")
    s3_secret_key: SecretStr = SecretStr("pa_minio_dev_secret")
    s3_presign_ttl_seconds: Annotated[int, Field(ge=30, le=3600)] = 300
    # TLS to object storage (split collector topology, D14): CA bundle to verify the server and
    # an optional client certificate/key pair for mutual TLS. Paths to mounted files.
    s3_ca_bundle: str | None = None
    s3_client_cert: str | None = None
    s3_client_key: str | None = None

    oidc_issuer: str = "http://localhost:58080/realms/pricing-assistance"
    oidc_audience: str = "pricing-api"
    oidc_jwks_url: str | None = None
    oidc_jwks_cache_seconds: Annotated[int, Field(ge=30)] = 600
    oidc_leeway_seconds: Annotated[int, Field(ge=0, le=120)] = 30

    catalog_max_upload_bytes: Annotated[int, Field(ge=1024)] = 5 * 1024 * 1024
    catalog_max_uncompressed_bytes: Annotated[int, Field(ge=1024)] = 50 * 1024 * 1024
    catalog_max_rows: Annotated[int, Field(ge=1)] = 20_000

    collector_user_agent: str = "PricingAssistance/0.1"
    collector_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 20.0
    browser_channel: str | None = None  # e.g. "chrome" to use an installed Google Chrome
    browser_executable_path: str | None = None
    browser_page_timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 30.0

    # AES-256-GCM keys for connector secrets, as "version:base64key" entries; the highest
    # version encrypts, all listed versions decrypt (key rotation). Dev default only.
    secret_encryption_keys: SecretStr = SecretStr("1:ZGV2LW9ubHktc2VjcmV0LWtleS0zMi1ieXRlcy0hISE=")

    idempotency_ttl_hours: Annotated[int, Field(ge=1, le=168)] = 24

    # Language-model use (docs/llm.md). Off by default; a provider is used only when enabled,
    # selected and listed as cleared by the operator's legal, data-location and compliance review.
    llm_enabled: bool = False
    llm_provider: Literal["null", "anthropic"] = "null"
    llm_cleared_providers: list[str] = Field(default_factory=list)
    anthropic_api_key: SecretStr | None = None
    llm_model_default: str = "claude-sonnet-5-5"  # extraction, matching, suggestions
    llm_model_rephrase: str = "claude-haiku-5-5"  # explanation wording
    llm_inference_geo: str | None = None
    llm_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 60.0
    llm_max_output_tokens: Annotated[int, Field(ge=256, le=16_384)] = 2_048
    llm_daily_token_budget: Annotated[int, Field(ge=0)] = 0  # per tenant; 0 refuses every call
    # model → {"input": Rial, "output": Rial} per million tokens; unset models report no cost
    llm_cost_rial_per_million_tokens: dict[str, dict[str, int]] = Field(default_factory=dict)

    otel_exporter_otlp_endpoint: str | None = None
    # Prometheus endpoint of the scheduler and worker processes (the API serves /metrics itself);
    # 0 disables it. Workers run one process per pod (see the Helm chart), so one port per pod.
    metrics_port: Annotated[int, Field(ge=0, le=65535)] = 0

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer}/protocol/openid-connect/certs"

    def secret_field_names(self) -> frozenset[str]:
        return frozenset(
            name
            for name, info in type(self).model_fields.items()
            if "SecretStr" in str(info.annotation)
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
