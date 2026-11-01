"""Public interface of the `llm` module.

Other modules may import only this file and `events.py`.
"""

from pricing_assistant.llm.adapters import (
    Completion,
    CompletionResult,
    LLMAdapter,
    LLMProviderError,
    NullLLMAdapter,
    RecordedAdapter,
)
from pricing_assistant.llm.budget import TokenBudget
from pricing_assistant.llm.deps import LLMDep
from pricing_assistant.llm.factory import build_adapter, build_llm
from pricing_assistant.llm.models import LLMCallRow
from pricing_assistant.llm.port import LLMPort, LLMResult, Outcome, require_value
from pricing_assistant.llm.schemas import (
    MAX_PAGE_CHARS,
    PUBLIC_ATTRIBUTE_KEYS,
    CandidateVariant,
    ExtractedAttributes,
    ExtractRequest,
    LLMTask,
    MatchProposal,
    MatchRequest,
    PageContent,
    Rephrased,
    RephraseRequest,
    RuleRequest,
    RuleSuggestion,
    UrlCandidate,
    UrlRequest,
    UrlSuggestions,
)
from pricing_assistant.llm.service import LLMService, ModelConfig

__all__ = [
    "MAX_PAGE_CHARS",
    "PUBLIC_ATTRIBUTE_KEYS",
    "CandidateVariant",
    "Completion",
    "CompletionResult",
    "ExtractRequest",
    "ExtractedAttributes",
    "LLMAdapter",
    "LLMCallRow",
    "LLMDep",
    "LLMPort",
    "LLMProviderError",
    "LLMResult",
    "LLMService",
    "LLMTask",
    "MatchProposal",
    "MatchRequest",
    "ModelConfig",
    "NullLLMAdapter",
    "Outcome",
    "PageContent",
    "RecordedAdapter",
    "RephraseRequest",
    "Rephrased",
    "RuleRequest",
    "RuleSuggestion",
    "TokenBudget",
    "UrlCandidate",
    "UrlRequest",
    "UrlSuggestions",
    "build_adapter",
    "build_llm",
    "require_value",
]
