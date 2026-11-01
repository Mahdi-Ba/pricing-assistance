"""FastAPI dependency for the LLM port (one instance per API process, set by ``create_app``)."""

from typing import Annotated

from fastapi import Depends, Request

from pricing_assistant.llm.port import LLMPort


def get_llm(request: Request) -> LLMPort:
    llm: LLMPort = request.app.state.llm
    return llm


LLMDep = Annotated[LLMPort, Depends(get_llm)]
