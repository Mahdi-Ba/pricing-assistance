"""LLM call log (task 8.6). Append-only: the app role has INSERT and SELECT only.

Only metadata is stored — task, provider, model, template version, tokens, latency, result and
correlation ID. Prompt and answer text are never stored or logged.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from pricing_assistant.core.db import Base


class CallResult(StrEnum):
    OK = "ok"
    INVALID = "invalid"
    ERROR = "error"
    BUDGET_EXHAUSTED = "budget_exhausted"


class LLMCallRow(Base):
    __tablename__ = "llm_call"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"))
    task: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    template_version: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
