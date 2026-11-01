"""Anthropic adapter contract (task 8.7): request shape and response handling.

Replays Messages API responses from ``fixtures/llm/anthropic`` (synthetic until the provider is
cleared, see the README there) through the real SDK client with a mock transport.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx2
import pytest

from pricing_assistant.llm.adapters import Completion, LLMProviderError
from pricing_assistant.llm.anthropic_adapter import FALLBACK_BETA, AnthropicAdapter
from pricing_assistant.llm.api import ExtractRequest, LLMService, LLMTask, Outcome
from pricing_assistant.llm.prompts import TEMPLATES, render
from pricing_assistant.llm.schemas import ExtractedAttributes, strict_json_schema

LLM_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "llm" / "anthropic"
TENANT = uuid.UUID("0192f0a0-0000-7000-8000-000000000001")


class Recorder:
    def __init__(self, fixture: str | None, status: int = 200) -> None:
        self.body = (LLM_FIXTURES / fixture).read_bytes() if fixture else b"{}"
        self.status = status
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.status != 200:
            error = {"type": "error", "error": {"type": "api_error", "message": "boom"}}
            return httpx2.Response(self.status, json=error)
        return httpx2.Response(200, content=self.body, headers={"content-type": "application/json"})

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.requests[-1].content)
        return result


def adapter(recorder: Recorder, **kwargs: Any) -> AnthropicAdapter:
    return AnthropicAdapter(
        api_key="test-key",
        timeout_seconds=5,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(recorder)),
        **kwargs,
    )


def extract_call(text: str = "سامسونگ 990 PRO 2TB") -> Completion:
    request = ExtractRequest(offer_text=text)
    return Completion(
        task=LLMTask.EXTRACT_ATTRIBUTES,
        model="claude-sonnet-5-5",
        system=TEMPLATES[LLMTask.EXTRACT_ATTRIBUTES].system,
        user=render(LLMTask.EXTRACT_ATTRIBUTES, request),
        schema=strict_json_schema(ExtractedAttributes),
        max_output_tokens=1024,
    )


async def test_request_uses_structured_output_without_tools() -> None:
    recorder = Recorder("extract_ok.json")
    result = await adapter(recorder).complete(extract_call())

    request = recorder.requests[0]
    assert request.url.path == "/v1/messages"
    assert FALLBACK_BETA in request.headers["anthropic-beta"]
    body = recorder.payload()
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 1024
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"] == strict_json_schema(ExtractedAttributes)
    assert body["fallbacks"] == "default"
    assert "tools" not in body
    assert "tool_choice" not in body
    assert "inference_geo" not in body
    assert body["system"].startswith(TEMPLATES[LLMTask.EXTRACT_ATTRIBUTES].system[:40])
    assert body["messages"][0]["content"].startswith("<untrusted_data")

    assert (result.input_tokens, result.output_tokens) == (612, 74)
    assert result.model == "claude-sonnet-5-5"
    assert not result.refused
    assert json.loads(result.text)["capacity"] == "2TB"


async def test_inference_region_is_sent_when_configured() -> None:
    recorder = Recorder("extract_ok.json")
    await adapter(recorder, inference_geo="eu").complete(extract_call())
    assert recorder.payload()["inference_geo"] == "eu"


async def test_refusal_and_truncation_are_reported() -> None:
    refused = await adapter(Recorder("refusal.json")).complete(extract_call())
    assert refused.refused
    assert refused.text == ""
    truncated = await adapter(Recorder("truncated.json")).complete(extract_call())
    assert truncated.truncated


@pytest.mark.parametrize("status", [400, 401, 429, 500, 529])
async def test_api_errors_become_provider_errors(status: int) -> None:
    with pytest.raises(LLMProviderError, match=f"HTTP {status}"):
        await adapter(Recorder(None, status=status)).complete(extract_call())


async def test_adapter_answer_passes_the_port_validation() -> None:
    llm = LLMService(adapter(Recorder("extract_ok.json")), budget=None)
    result = await llm.extract_attributes(TENANT, ExtractRequest(offer_text="990 PRO"))
    assert result.outcome is Outcome.OK
    assert result.value is not None
    assert result.value.warranty_provider == "آواژنگ"
