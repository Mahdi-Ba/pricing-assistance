"""Provider selection by configuration (tasks 8.7, 8.8).

The compliance gate is explicit: an external provider is built only when ``llm_enabled`` is set,
it is the selected ``llm_provider`` and it is listed in ``llm_cleared_providers`` (the record of
Tunoo's legal, data-location and compliance sign-off). Anything else yields the null adapter.
"""

from collections.abc import Callable

from redis.asyncio import Redis

from pricing_assistant.core.db import Database
from pricing_assistant.core.logging import get_logger
from pricing_assistant.core.settings import Settings
from pricing_assistant.llm.adapters import LLMAdapter, NullLLMAdapter
from pricing_assistant.llm.anthropic_adapter import AnthropicAdapter
from pricing_assistant.llm.budget import TokenBudget
from pricing_assistant.llm.service import DatabaseCallRecorder, LLMService, ModelConfig

log = get_logger(__name__)


def build_adapter(settings: Settings) -> LLMAdapter:
    provider = settings.llm_provider
    if not settings.llm_enabled or provider == "null":
        return NullLLMAdapter()
    if provider not in settings.llm_cleared_providers:
        log.warning("llm.provider_not_cleared", provider=provider)
        return NullLLMAdapter()
    # provider == "anthropic" (the only external provider so far)
    if settings.anthropic_api_key is None:
        log.warning("llm.provider_misconfigured", provider=provider, missing="api_key")
        return NullLLMAdapter()
    return AnthropicAdapter(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout_seconds=settings.llm_timeout_seconds,
        inference_geo=settings.llm_inference_geo,
    )


def build_llm(
    settings: Settings,
    *,
    redis: Callable[[], Redis],
    database: Callable[[], Database],
    adapter: LLMAdapter | None = None,
) -> LLMService:
    return LLMService(
        adapter or build_adapter(settings),
        budget=TokenBudget(redis, settings.llm_daily_token_budget),
        recorder=DatabaseCallRecorder(database),
        models=ModelConfig(
            default=settings.llm_model_default,
            rephrase=settings.llm_model_rephrase,
            max_output_tokens=settings.llm_max_output_tokens,
        ),
        timeout_seconds=settings.llm_timeout_seconds,
    )
