# Language-model assistance

The pricing assistant works completely **without** a language model. The rule-based pipeline plus human confirmation is the baseline. The LLM is an optional helper for five bounded tasks. Its answers are always suggestions that a person approves, and it never takes part in a price calculation.

**Status:** disabled. No provider has passed the operator's legal, data-location and compliance review yet (business question Q-T2).

## 1. What the model may do

| Task | Input sent | Output | What happens with it |
|---|---|---|---|
| `extract_attributes` | Offer title | Brand, model, capacity, … (strict schema) | Fills attributes the rules could not find, tagged `source: llm`. Rule values always win. Called once per distinct rule result. |
| `propose_match` | Offer title + up to 5 candidate variants (brand, model, name, public attributes) | Candidate ID or `null`, confidence, rationale | Only for offers held back for *missing* attributes. Can move the offer to `proposed` (`decided_by: llm`, confidence ≤ 90 %), never to `confirmed`. Never overrides an attribute or condition mismatch. |
| `rephrase_explanation` | The deterministic Persian explanation | Reworded text | Stored as `explanation_llm` only if it contains exactly the same numbers. The deterministic `explanation` is always kept and shown when no wording exists. |
| `suggest_extraction_rule` | Up to 3 stored sample pages of one cleared source, with scripts/styles removed | CSS selector rule | Stored as a `proposed` extraction-rule version with its results on the samples. Inactive until an admin approves it. |
| `suggest_offer_urls` | A variant's identity + the on-domain links of the source's search-results page | Up to 5 URLs from that page | Stored as `suggested` tracked offers. Not scheduled until an expert confirms them. |

The model **never**:

- reads prices or stock for collection (no LLM fallback in extraction)
- computes the market reference, floor, ceiling, suggested price or profit (an import contract forbids `pricing.engine`, `inputs`, `service` and `explain` from importing `llm`)
- fetches anything: every page it sees was fetched earlier by a connector, under the source's clearance and quota
- gets tools or function calling
- confirms a match, activates a rule, schedules an offer or changes a price

## 2. Data boundaries

Requests are built from allow-listed Pydantic models (`llm/schemas.py`). Every request model forbids extra fields. A candidate variant accepts only these attributes: `capacity`, `generation`, `frequency`, `colour_edition`, `warranty_provider` and `warranty_months`. Purchase cost, margins, fees, VAT, profit rules, supplier data and personal data have no field, so they cannot be serialized (see `tests/unit/test_llm_port.py`).

One input needs attention in the compliance review. The deterministic explanation sent for **rewording** includes the market price, the suggested price and the **profit floor**. The floor is derived from cost and margin. The spec's "number altered" scenario expects the floor in the reworded text. If the review decides the floor must not leave the system, disable rewording (it is optional) or drop the floor sentence from the rewording input.

Third-party text (titles, page content, seller names) is wrapped in `<untrusted_data>` blocks. Tag-like sequences inside the content are neutralized, so the content cannot close its block early. The system prompt says that delimited content is data and never an instruction. Prompt and answer text are never logged.

## 3. Validation and fallback

Every answer goes through the same path (`llm/service.py`):

1. If the adapter is disabled, the result is `disabled` and no call is made.
2. If the tenant's daily token budget is used up, the result is `budget_exhausted`.
3. The call has a hard timeout. A provider error, refusal or truncation gives `error`.
4. The answer is parsed in strict mode against the task's schema: no unknown fields and no type coercion. Then the task's own checks run:
   - the proposed candidate ID is one that was sent
   - rewording keeps the multiset of numbers (Persian, Arabic-Indic and ASCII digits; thousands and decimal separators normalized)
   - a suggested rule parses
   - suggested URLs appear on the fetched page

   A failed check gives `invalid`.
5. Only `ok` carries a value. On any other result the caller falls back: rule attributes, the human queue, the deterministic text, or a problem response for user-requested suggestions (`409 llm_disabled`, `429 llm_budget_exhausted`, `503 llm_no_suggestion`).

## 4. Observability and budget

- **`llm_call` table** (append-only, tenant-scoped): task, provider, model actually used, prompt template version, input/output tokens, latency, result (`ok`, `invalid`, `error`, `budget_exhausted`), a short reason with no content, and correlation ID.
- **Metrics:** `pa_llm_calls_total{task,result}`, `pa_llm_tokens_total{task,direction}`, `pa_llm_latency_seconds{task}`.
- **Budget:** `PA_LLM_DAILY_TOKEN_BUDGET` tokens per tenant per Tehran calendar day, counted in Redis. The budget is checked before a call and charged with the actual usage afterwards, so one call can overshoot by its own size. `0` refuses every call.

Prompt templates are versioned (`extract-v1`, `match-v1`, …) in `llm/prompts.py`. Any wording change requires a version bump.

## 5. Enabling a provider (compliance gate)

A provider is used only when **all three** settings agree. Anything else falls back to the null adapter.

```bash
PA_LLM_ENABLED=true
PA_LLM_PROVIDER=anthropic
PA_LLM_CLEARED_PROVIDERS='["anthropic"]'   # record of the compliance sign-off
PA_ANTHROPIC_API_KEY=...                   # secret; never logged
PA_LLM_DAILY_TOKEN_BUDGET=200000
# optional
PA_LLM_INFERENCE_GEO=eu                    # pin the processing region if the review requires it
PA_LLM_MODEL_DEFAULT=claude-sonnet-5-5     # extraction, matching, suggestions
PA_LLM_MODEL_REPHRASE=claude-haiku-5-5     # explanation wording
PA_LLM_TIMEOUT_SECONDS=60
```

Before you add a provider to `PA_LLM_CLEARED_PROVIDERS`:

1. Get written legal, data-location and compliance approval, and record its reference in the deployment change.
2. Replace the synthetic responses in `fixtures/llm/anthropic/` with recorded ones (prompt text removed), then run `tests/contract/test_anthropic_adapter.py`.
3. Run the pilot evaluation on the golden titles (`fixtures/matching/golden_titles.jsonl`) and review the `llm_call` results.

### Anthropic adapter

`llm/anthropic_adapter.py` uses the Messages API with structured JSON output (`output_config.format` = the task's strict JSON schema). It sends no `tools`. It enables **server-side fallback** (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`): if the requested model declines a request for policy reasons, the API retries it on that model's default substitute model. On models without fallback support, the request runs on the requested model alone. The model that actually answered is logged in `llm_call.model`. The SDK retries `429`/`5xx`/connection errors twice; anything left falls back.

## 6. Switching providers

Callers depend only on `LLMPort` (`llm/port.py`). An adapter implements `complete(Completion) -> CompletionResult`: system text, user text and a strict JSON schema in; raw JSON text and token usage out. It must not add tools. To add a provider (for example, the self-hosted open-weights fallback from design D9):

1. Implement the adapter next to `anthropic_adapter.py`. Map provider errors to `LLMProviderError`, and report refusals and truncation.
2. Add it to `Settings.llm_provider` and `llm/factory.py`.
3. Add a contract test with recorded responses.

Schemas, prompts, validation, budget and logging stay the same. `tests/integration/test_llm_assistance.py::test_provider_switch_keeps_schemas_and_validation` runs the same pipeline with the null adapter and two recorded providers.

## 7. Operations

| Feature | Endpoint | Where it runs |
|---|---|---|
| Rule suggestion | `POST /api/v1/sources/{id}/extraction-rules/suggest` (admin) | API process; reads stored samples, fetches nothing |
| Offer-URL suggestion | `POST /api/v1/sources/{id}/offer-url-suggestions` (expert) → `202` + `request_id` | `worker-collect` (`sources.suggest_offer_urls`); the outcome is audited as `source.offer_urls.suggested` |
| Attribute extraction, match proposal | event-driven (`matching.normalize`, `matching.match`) | `worker-process` |
| Explanation wording | `pricing.rephrase` on `recommendation.created` | `worker-process` |

Offer-URL suggestion needs an `html` source whose connector config has `search_url_template` with `{query}`, on the source's domain, for example `https://www.example.ir/search?q={query}`. The search fetch takes a quota slot like every other request. A `blocked` answer pauses the source.
