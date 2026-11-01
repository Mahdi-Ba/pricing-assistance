"""Anthropic Claude adapter: structured JSON output, no tools (task 8.7).

Requests use the Messages API with ``output_config.format`` set to the task's strict JSON
schema, so the answer is constrained JSON; the port still validates it. No ``tools`` are ever
sent. Server-side fallback (``fallbacks="default"``) lets the API retry a policy-declined
request on the model's default substitute; on a model without fallback support the request
simply runs alone, and a remaining refusal is reported as ``refused``. ``inference_geo`` pins
the processing region when the compliance review requires it.

The SDK retries 429/5xx/connection errors (``max_retries``); anything left is raised as
:class:`LLMProviderError` so the port can fall back.
"""

import anthropic
import httpx2
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

from pricing_assistant.llm.adapters import Completion, CompletionResult, LLMProviderError

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicAdapter:
    name = "anthropic"
    enabled = True

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float,
        max_retries: int = 2,
        inference_geo: str | None = None,
        base_url: str | None = None,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
            base_url=base_url,
            http_client=http_client,
        )
        self._inference_geo = inference_geo

    async def complete(self, call: Completion) -> CompletionResult:
        messages: list[BetaMessageParam] = [{"role": "user", "content": call.user}]
        output: BetaOutputConfigParam = {"format": {"type": "json_schema", "schema": call.schema}}
        try:
            response = await self._client.beta.messages.create(
                model=call.model,
                max_tokens=call.max_output_tokens,
                system=call.system,
                messages=messages,
                output_config=output,
                fallbacks="default",
                inference_geo=self._inference_geo or anthropic.omit,
                betas=[FALLBACK_BETA],
            )
        except anthropic.APIError as exc:
            status = getattr(exc, "status_code", None)
            raise LLMProviderError(
                f"{type(exc).__name__}" + (f" (HTTP {status})" if status else "")
            ) from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        return CompletionResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            refused=response.stop_reason == "refusal",
            truncated=response.stop_reason == "max_tokens",
        )

    async def aclose(self) -> None:
        await self._client.close()
