"""Prometheus metrics for LLM calls (design D13)."""

from prometheus_client import Counter, Histogram

LLM_CALLS = Counter("pa_llm_calls_total", "LLM calls by task and result", ["task", "result"])
LLM_TOKENS = Counter(
    "pa_llm_tokens_total", "LLM tokens by task and direction", ["task", "direction"]
)
LLM_LATENCY_SECONDS = Histogram(
    "pa_llm_latency_seconds",
    "LLM call latency",
    ["task"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)
