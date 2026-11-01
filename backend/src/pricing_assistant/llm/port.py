"""The LLM port: the only way any module reaches a language model (task 8.1).

Every operation returns an :class:`LLMResult`. Only ``outcome == ok`` carries a value; every
other outcome means "fall back": rule-based processing, the deterministic text, or the human
queue. Callers never see provider exceptions.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from pricing_assistant.core.errors import Conflict, ServiceUnavailable, TooManyRequests
from pricing_assistant.llm.schemas import (
    ExtractedAttributes,
    ExtractRequest,
    MatchProposal,
    MatchRequest,
    Rephrased,
    RephraseRequest,
    RuleRequest,
    RuleSuggestion,
    UrlRequest,
    UrlSuggestions,
)

# a caller's domain check on a schema-valid answer: None if acceptable, else a short reason
Check = Callable[[BaseModel], str | None]


class Outcome(StrEnum):
    OK = "ok"
    DISABLED = "disabled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INVALID = "invalid"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LLMResult[T]:
    outcome: Outcome
    value: T | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK and self.value is not None


def require_value[T](result: LLMResult[T]) -> T:
    """For user-requested suggestions: the value, or a problem response explaining why not."""
    if result.ok and result.value is not None:
        return result.value
    if result.outcome is Outcome.DISABLED:
        raise Conflict(
            "Language-model assistance is not enabled",
            code="llm_disabled",
            message_fa="دستیار هوش مصنوعی فعال نیست؛ این کار را دستی انجام دهید.",
        )
    if result.outcome is Outcome.BUDGET_EXHAUSTED:
        raise TooManyRequests(
            "The daily language-model budget is used up",
            code="llm_budget_exhausted",
            message_fa="سهمیه روزانه دستیار هوش مصنوعی تمام شده است؛ فردا دوباره تلاش کنید.",
        )
    raise ServiceUnavailable(
        "The language model gave no usable suggestion",
        code="llm_no_suggestion",
        message_fa="پیشنهاد قابل‌استفاده‌ای دریافت نشد؛ دوباره تلاش کنید یا دستی ادامه دهید.",
    )


class LLMPort(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def extract_attributes(
        self, tenant_id: uuid.UUID, request: ExtractRequest
    ) -> LLMResult[ExtractedAttributes]: ...

    async def propose_match(
        self, tenant_id: uuid.UUID, request: MatchRequest
    ) -> LLMResult[MatchProposal]: ...

    async def rephrase_explanation(
        self, tenant_id: uuid.UUID, request: RephraseRequest
    ) -> LLMResult[Rephrased]: ...

    async def suggest_extraction_rule(
        self, tenant_id: uuid.UUID, request: RuleRequest, check: Check | None = None
    ) -> LLMResult[RuleSuggestion]: ...

    async def suggest_offer_urls(
        self, tenant_id: uuid.UUID, request: UrlRequest, check: Check | None = None
    ) -> LLMResult[UrlSuggestions]: ...
