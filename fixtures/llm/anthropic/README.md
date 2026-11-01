# Anthropic Messages API responses (SYNTHETIC)

These files follow the Messages API response format but were **written by hand**, not recorded
from the live API: no external LLM provider has passed the operator's compliance review yet (Q-T2), so
no real traffic may be sent. Replace them with recorded responses (prompt text removed) once the
provider is cleared; the contract tests in `backend/tests/contract/test_anthropic_adapter.py`
must keep passing.

- `extract_ok.json` — structured-output answer for `extract_attributes`.
- `refusal.json` — a request declined after server-side fallback (`stop_reason: refusal`).
- `truncated.json` — an answer cut off at `max_tokens`.
