"""Provider adapters behind the LLM port (tasks 8.1, 8.7).

An adapter turns one :class:`Completion` (system text, delimited user text, strict JSON schema)
into raw JSON text plus token usage. Adapters never get tools and never act on the output; the
port validates everything they return.

- :class:`NullLLMAdapter` is the default: disabled, makes no call.
- :class:`RecordedAdapter` replays recorded answers (tests, provider-switch checks, demos).
- ``AnthropicAdapter`` (``anthropic_adapter.py``) is the candidate external provider, used only
  after the compliance sign-off (see ``docs/llm.md``).
"""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pricing_assistant.llm.schemas import LLMTask


@dataclass(frozen=True, slots=True)
class Completion:
    task: LLMTask
    model: str
    system: str
    user: str
    schema: dict[str, Any] = field(repr=False)
    max_output_tokens: int

    def fingerprint(self) -> str:
        """Stable hash of the prompt, used to key recorded responses."""
        return hashlib.sha256(f"{self.system}\x00{self.user}".encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    refused: bool = False
    truncated: bool = False


class LLMProviderError(Exception):
    """The provider could not produce an answer (network, quota, server error)."""


class LLMAdapter(Protocol):
    name: str
    enabled: bool

    async def complete(self, call: Completion) -> CompletionResult: ...

    async def aclose(self) -> None: ...


class NullLLMAdapter:
    """No provider cleared: the port reports ``disabled`` and never calls this."""

    name = "null"
    enabled = False

    async def complete(self, call: Completion) -> CompletionResult:
        raise LLMProviderError("LLM use is disabled")

    async def aclose(self) -> None:
        return None


Recorded = str | Callable[[Completion], str]


class RecordedAdapter:
    """Replays recorded raw answers per task; an unrecorded task fails like a provider error."""

    enabled = True

    def __init__(
        self,
        responses: Mapping[LLMTask, Recorded],
        *,
        name: str = "recorded",
        tokens: tuple[int, int] = (100, 50),
    ) -> None:
        self.name = name
        self._responses = dict(responses)
        self._tokens = tokens
        self.calls: list[Completion] = []

    async def complete(self, call: Completion) -> CompletionResult:
        self.calls.append(call)
        recorded = self._responses.get(call.task)
        if recorded is None:
            raise LLMProviderError(f"no recorded response for {call.task}")
        text = recorded(call) if callable(recorded) else recorded
        return CompletionResult(
            text=text, input_tokens=self._tokens[0], output_tokens=self._tokens[1], model=call.model
        )

    async def aclose(self) -> None:
        return None
