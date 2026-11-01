import json
import logging
from pathlib import Path

import pytest
import structlog

from pricing_assistant.core.logging import REDACTED, configure_logging, get_logger
from pricing_assistant.core.settings import Settings

SECRET = "s3cr3t-value-that-must-not-leak"


def test_secret_fields_are_redacted_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PA_DATABASE_APP_URL", f"postgresql+asyncpg://pa_app:{SECRET}@db/pricing")
    monkeypatch.setenv("PA_ANTHROPIC_API_KEY", SECRET)
    settings = Settings()

    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert SECRET not in settings.model_dump_json()
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == SECRET
    assert {"database_app_url", "anthropic_api_key", "s3_secret_key"} <= (
        settings.secret_field_names()
    )


def test_secrets_are_read_from_mounted_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PA_REDIS_URL", raising=False)  # environment wins over secret files
    (tmp_path / "pa_redis_url").write_text("redis://:filepass@redis:6379/0")
    monkeypatch.setitem(Settings.model_config, "secrets_dir", str(tmp_path))
    settings = Settings()

    assert settings.redis_url.get_secret_value() == "redis://:filepass@redis:6379/0"


def test_log_output_redacts_secrets(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json=True, service="test")
    settings = Settings(anthropic_api_key=SECRET)  # type: ignore[arg-type]
    log = get_logger("test")

    log.info("settings.loaded", settings=settings.model_dump(), password=SECRET)
    log.info("connect", dsn=settings.database_app_url, nested={"api_key": SECRET, "ok": 1})
    logging.getLogger("stdlib").info("stdlib %s", "message")

    out = capsys.readouterr().out
    assert SECRET not in out
    lines = [json.loads(line) for line in out.splitlines()]
    assert lines[0]["password"] == REDACTED
    assert lines[1]["dsn"] == REDACTED
    assert lines[1]["nested"] == {"api_key": REDACTED, "ok": 1}
    assert lines[2]["event"] == "stdlib message"
    structlog.contextvars.clear_contextvars()
