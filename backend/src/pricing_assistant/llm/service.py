"""The LLM port implementation: gate, budget, prompt, call, validate, log (tasks 8.1–8.6).

One path for every task:

1. Disabled adapter → ``disabled``; no call, nothing logged.
2. Daily token budget used up → ``budget_exhausted`` (logged).
3. Render the versioned template; untrusted text is delimited.
4. Call the adapter under a hard timeout; provider failure, refusal or truncation → ``error``.
5. Charge the tokens; parse the answer against the strict schema, then the task's own checks
   (candidate ids, number preservation, URLs present on the page) → ``invalid`` on failure.
6. Log task, provider, model, template version, tokens, latency, result and correlation ID —
   never prompt or answer text.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from pricing_assistant.core.correlation import get_correlation_id
from pricing_assistant.core.db import Database
from pricing_assistant.core.ids import new_id
from pricing_assistant.core.logging import get_logger
from pricing_assistant.llm.adapters import Completion, CompletionResult, LLMAdapter
from pricing_assistant.llm.budget import BudgetExhausted, TokenBudget
from pricing_assistant.llm.metrics import LLM_CALLS, LLM_LATENCY_SECONDS, LLM_TOKENS
from pricing_assistant.llm.models import CallResult, LLMCallRow
from pricing_assistant.llm.port import Check, LLMResult, Outcome
from pricing_assistant.llm.prompts import TEMPLATES, render
from pricing_assistant.llm.schemas import (
    ExtractedAttributes,
    ExtractRequest,
    LLMTask,
    MatchProposal,
    MatchRequest,
    Rephrased,
    RephraseRequest,
    RuleRequest,
    RuleSuggestion,
    UrlRequest,
    UrlSuggestions,
    strict_json_schema,
)
from pricing_assistant.llm.validators import numbers_preserved

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    default: str = "claude-sonnet-5-5"
    rephrase: str = "claude-haiku-5-5"
    max_output_tokens: int = 2_048

    def for_task(self, task: LLMTask) -> str:
        return self.rephrase if task is LLMTask.REPHRASE_EXPLANATION else self.default


@dataclass(frozen=True, slots=True)
class CallLog:
    task: LLMTask
    provider: str
    model: str
    template_version: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    result: CallResult
    detail: str | None
    correlation_id: str


class DatabaseCallRecorder:
    """Writes the call log in its own transaction, so it survives the caller's rollback."""

    def __init__(self, database: Callable[[], Database]) -> None:
        self._database = database

    async def __call__(self, tenant_id: uuid.UUID, entry: CallLog) -> None:
        async with self._database().tenant_session(tenant_id) as session:
            session.add(
                LLMCallRow(
                    id=new_id(),
                    tenant_id=tenant_id,
                    task=entry.task.value,
                    provider=entry.provider,
                    model=entry.model,
                    template_version=entry.template_version,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    latency_ms=entry.latency_ms,
                    result=entry.result.value,
                    detail=entry.detail,
                    correlation_id=entry.correlation_id,
                )
            )


Recorder = Callable[[uuid.UUID, CallLog], Awaitable[None]]


def _validation_detail(exc: ValidationError) -> str:
    """Error locations and types only; input values may be third-party content."""
    parts = [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}:{e['type']}" for e in exc.errors()]
    return "; ".join(parts)[:500]


class LLMService:
    def __init__(
        self,
        adapter: LLMAdapter,
        *,
        budget: TokenBudget | None,
        recorder: Recorder | None = None,
        models: ModelConfig | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._adapter = adapter
        self._budget = budget
        self._recorder = recorder
        self._models = models or ModelConfig()
        self._timeout = timeout_seconds

    @property
    def enabled(self) -> bool:
        return self._adapter.enabled

    @property
    def provider(self) -> str:
        return self._adapter.name

    # --- operations ------------------------------------------------------------------------

    async def extract_attributes(
        self, tenant_id: uuid.UUID, request: ExtractRequest
    ) -> LLMResult[ExtractedAttributes]:
        return await self._run(tenant_id, LLMTask.EXTRACT_ATTRIBUTES, request, ExtractedAttributes)

    async def propose_match(
        self, tenant_id: uuid.UUID, request: MatchRequest
    ) -> LLMResult[MatchProposal]:
        allowed = {c.id for c in request.candidates}

        def known_candidate(value: BaseModel) -> str | None:
            assert isinstance(value, MatchProposal)  # noqa: S101 - narrowed by _run
            if value.variant_id is not None and value.variant_id not in allowed:
                return "variant_id is not one of the candidates"
            return None

        return await self._run(
            tenant_id, LLMTask.PROPOSE_MATCH, request, MatchProposal, known_candidate
        )

    async def rephrase_explanation(
        self, tenant_id: uuid.UUID, request: RephraseRequest
    ) -> LLMResult[Rephrased]:
        def same_numbers(value: BaseModel) -> str | None:
            assert isinstance(value, Rephrased)  # noqa: S101 - narrowed by _run
            if not numbers_preserved(request.text, value.text):
                return "numbers changed"
            return None

        return await self._run(
            tenant_id, LLMTask.REPHRASE_EXPLANATION, request, Rephrased, same_numbers
        )

    async def suggest_extraction_rule(
        self, tenant_id: uuid.UUID, request: RuleRequest, check: Check | None = None
    ) -> LLMResult[RuleSuggestion]:
        return await self._run(
            tenant_id, LLMTask.SUGGEST_EXTRACTION_RULE, request, RuleSuggestion, check
        )

    async def suggest_offer_urls(
        self, tenant_id: uuid.UUID, request: UrlRequest, check: Check | None = None
    ) -> LLMResult[UrlSuggestions]:
        return await self._run(
            tenant_id, LLMTask.SUGGEST_OFFER_URLS, request, UrlSuggestions, check
        )

    # --- the single call path --------------------------------------------------------------

    async def _run[T: BaseModel](
        self,
        tenant_id: uuid.UUID,
        task: LLMTask,
        request: BaseModel,
        response_model: type[T],
        check: Check | None = None,
    ) -> LLMResult[T]:
        if not self._adapter.enabled:
            return LLMResult(Outcome.DISABLED)
        template = TEMPLATES[task]
        model = self._models.for_task(task)
        started = time.perf_counter()

        async def finish(
            result: CallResult, detail: str | None = None, usage: CompletionResult | None = None
        ) -> None:
            await self._log(
                tenant_id,
                CallLog(
                    task=task,
                    provider=self._adapter.name,
                    model=usage.model if usage else model,
                    template_version=template.version,
                    input_tokens=usage.input_tokens if usage else 0,
                    output_tokens=usage.output_tokens if usage else 0,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    result=result,
                    detail=detail,
                    correlation_id=get_correlation_id(),
                ),
            )

        if self._budget is not None:
            try:
                await self._budget.check(tenant_id)
            except BudgetExhausted:
                await finish(CallResult.BUDGET_EXHAUSTED)
                return LLMResult(Outcome.BUDGET_EXHAUSTED)

        call = Completion(
            task=task,
            model=model,
            system=template.system,
            user=render(task, request),
            schema=strict_json_schema(response_model),
            max_output_tokens=self._models.max_output_tokens,
        )
        try:
            async with asyncio.timeout(self._timeout):
                completion = await self._adapter.complete(call)
        except TimeoutError:
            await finish(CallResult.ERROR, "timeout")
            return LLMResult(Outcome.ERROR)
        except Exception as exc:  # any provider failure falls back, never propagates
            await finish(
                CallResult.ERROR, type(exc).__name__ + (f": {exc}"[:200] if str(exc) else "")
            )
            return LLMResult(Outcome.ERROR)

        if self._budget is not None:
            await self._budget.charge(tenant_id, completion.input_tokens + completion.output_tokens)
        if completion.refused or completion.truncated:
            await finish(
                CallResult.ERROR, "refusal" if completion.refused else "max_tokens", completion
            )
            return LLMResult(Outcome.ERROR)
        try:
            value = response_model.model_validate_json(completion.text, strict=True)
        except ValidationError as exc:
            await finish(CallResult.INVALID, _validation_detail(exc), completion)
            return LLMResult(Outcome.INVALID)
        problem = check(value) if check is not None else None
        if problem is not None:
            await finish(CallResult.INVALID, problem[:500], completion)
            return LLMResult(Outcome.INVALID)
        await finish(CallResult.OK, None, completion)
        return LLMResult(Outcome.OK, value)

    async def _log(self, tenant_id: uuid.UUID, entry: CallLog) -> None:
        LLM_CALLS.labels(entry.task.value, entry.result.value).inc()
        LLM_TOKENS.labels(entry.task.value, "input").inc(entry.input_tokens)
        LLM_TOKENS.labels(entry.task.value, "output").inc(entry.output_tokens)
        LLM_LATENCY_SECONDS.labels(entry.task.value).observe(entry.latency_ms / 1000)
        log.info(
            "llm.call",
            tenant_id=str(tenant_id),
            task=entry.task.value,
            provider=entry.provider,
            model=entry.model,
            template_version=entry.template_version,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            latency_ms=entry.latency_ms,
            result=entry.result.value,
            detail=entry.detail,
            correlation_id=entry.correlation_id,
        )
        if self._recorder is None:
            return
        try:
            await self._recorder(tenant_id, entry)
        except Exception:  # a lost log row must not fail the business task
            log.exception("llm.call_log_failed", task=entry.task.value)
