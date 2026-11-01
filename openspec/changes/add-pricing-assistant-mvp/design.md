# Design

## Context

- The repository is greenfield. It holds only OpenSpec scaffolding and no application code, so every structural decision is made here.
- The source PRD (`pricing-assistant.html`, v1.0) proposes React/Next.js, Python/FastAPI, PostgreSQL, HTTP+HTML parser, Playwright workers and Redis + a job queue. It says that "one central application plus background workers is enough to start." This design keeps that stack.
- The PRD's processing flow is: source connector → validation → normalization → product matching → rule calculation → expert queue.
- The product is a multi-tenant SaaS. Scale for phase A/B: one store (one tenant), 100–300 variants, 1–5 users (`admin`, `expert`), and up to four candidate competitor sources (Torob product pages, Digikala product pages, Lion Computer, Meghdad IT), each subject to access clearance, plus our own storefront and our Torob listing. This is small, but the PRD requires each source to have its own connector, so that one site's change does not stop pricing logic or other sources.
- Platform standards apply: separate orchestration from business logic, event-driven communication, idempotent operations, auditability, tenant isolation, Kubernetes/OpenShift compatibility, and bounded, validated LLM use.
- Requirements live in `specs/`; business questions and their answers (2026-10-25) are in `business-questions.md`.

## Goals / Non-Goals

**Goals:**

- A modular codebase. Modules map 1:1 to the spec capabilities and talk only through typed interfaces and domain events, so any module can later become its own deployable without a rewrite.
- A deterministic, replayable recommendation path: same inputs give the same output, and every output is traceable to its inputs.
- Fault isolation per source. Retries, quotas and idempotency are built into collection.
- Multi-tenant data model from day one, even though the pilot runs one tenant.
- A deployment that runs on plain Kubernetes and OpenShift (non-root, arbitrary UID).

**Non-Goals:**

- Splitting into separately deployed microservices now. The modules are deployed as one API plus role-specific worker processes from one codebase.
- Agentic or LLM-driven orchestration. The pipeline is a deterministic event flow; the LLM is an optional, bounded helper whose outputs are always suggestions (see `specs/llm-assistance`). It never reads operational prices.
- Out-of-app notifications (SMS, email, Telegram), multi-language UI, stock- or sales-driven pricing rules.
- Real-time (sub-minute) monitoring guarantees. Intervals are configuration, to be tuned after source qualification.
- Store write integrations of any kind.
- Native mobile UI. The web UI must be usable on tablet width but is optimized for desktop.

## Decisions

### D1. Modular monolith with role-specific processes

The backend is one Python package with bounded modules: `catalog`, `sources` (registry and connectors), `collection`, `matching`, `pricing` (recommendation engine), `decisions`, `workspace` (query/read models for the UI), `llm`, `iam`, `audit` and `reporting`. One container image is built and run as different process roles:

| Role | Entrypoint | Responsibility |
|---|---|---|
| `api` | FastAPI (uvicorn) | REST API, auth, commands, queries |
| `scheduler` | single replica (leader via Postgres advisory lock) | enqueues due fetches, verification timeouts, outbox relay |
| `worker-collect` | Dramatiq | API/HTML fetches |
| `worker-browser` | Dramatiq + Playwright image | rendered-page fetches only |
| `worker-process` | Dramatiq | normalization, matching, recommendation, reporting |

Modules may import only another module's `api.py` (public interface) and `events.py`. An import-linter contract checked in CI enforces this.

*Alternatives*: separate microservices per capability. Rejected for phase A/B: the operational cost is too high for 300 SKUs, and the module boundaries plus outbox events keep a later split cheap. A single process with in-process tasks was also rejected: browser fetches would starve API latency, and the PRD asks for background workers.

### D2. Technology stack

- **Backend**: Python 3.12, FastAPI, Pydantic v2 (all DTOs and event payloads), SQLAlchemy 2 (async) + Alembic, `httpx` for HTTP connectors, `selectolax` plus `extruct` (JSON-LD/microdata) for HTML, Playwright (Chromium) for rendered pages, `structlog` JSON logs, OpenTelemetry tracing, and the Prometheus client.
- **Queue**: Dramatiq with the Redis broker. It provides retries with backoff, dead-letter, time limits and an asyncio middleware.
  - Alternative: Celery. Rejected as heavier, with weaker typing ergonomics.
  - Alternative: arq. Rejected because it has less built-in retry and DLQ support.
- **Storage**: PostgreSQL 16 (system of record, RLS), Redis 7 (broker, token buckets, LLM budget counters), S3-compatible object storage (MinIO in dev and on-prem) for evidence snapshots.
- **Frontend**: Next.js (App Router) + TypeScript, TanStack Query, Zod (API response validation), Tailwind with logical properties for RTL, Vazirmatn font. API types are generated from the FastAPI OpenAPI schema (`openapi-typescript`), so frontend and backend contracts cannot drift.
- **Identity**: OIDC via Keycloak (deployable on OpenShift; replaceable with any OIDC IdP). Next.js uses Auth.js as a backend-for-frontend: tokens stay in the server-side session (httpOnly cookie) and the browser never holds an access token. FastAPI validates JWTs (issuer, audience, signature via JWKS) and reads `tenant_id` and roles from claims.

### D3. Event-driven pipeline with transactional outbox

State changes write the domain row and an `outbox_events` row in the same transaction. The scheduler's outbox relay publishes events to Dramatiq queues and marks them dispatched, giving at-least-once delivery. Every consumer is idempotent, keyed by `event_id` in a `processed_events` table.

```
fetch.requested ─▶ [collect] ─▶ observation.recorded | fetch.failed
observation.recorded ─▶ [process] normalize ─▶ offer.attributes.updated
offer.attributes.updated ─▶ [process] match ─▶ match.changed
match.changed | observation.recorded | catalog.cost.changed | rule.version.created
      ─▶ [process] recompute(variant) ─▶ recommendation.created (supersedes previous)
decision.recorded ─▶ [scheduler] verification window timer
observation.recorded (own-store) ─▶ [process] outcome verification
```

Event envelope (Pydantic): `event_id (UUIDv7)`, `type`, `version`, `tenant_id`, `occurred_at`, `correlation_id`, `causation_id`, `payload`. Recomputation is debounced per variant: a `variant_id` + 5-second coalescing key means a burst of observations produces one recommendation.

*Alternatives*: direct synchronous calls between modules. Rejected: they couple source failures to pricing (the PRD forbids this) and lose replayability. Kafka or NATS was also rejected: an extra broker is not justified at pilot scale, and the outbox can relay to one later without changing producers.

### D4. Data model and invariants

All tables carry `tenant_id`. Postgres Row-Level Security policies use `current_setting('app.tenant_id')`, which the session sets at transaction start from the authenticated principal. Worker sessions set it from the event envelope.

The application connects as a non-owner role, so RLS cannot be bypassed.

Core entities (from the PRD's data model):

- `product`, `variant` (SKU, MPN/GTIN, attributes incl. colour/edition, importance tier, our current price, `cost_status`), `cost_record` (versioned; import ID, uploader, previous value, `suspect_unit` hold state).
- `profit_rule_version`: immutable. Fields: scope (default/category/variant), min_margin_bp, fee_rate_bp, vat_rate_bp (required at default scope), ceiling, undercut_step, hold_tolerance_bp, max_data_age per tier (A/B/C), rounding_step, outlier_threshold_bp, min_qualifying_offers, competitor set (allowed sellers per source).
- `source` (registry, lifecycle status, method, currency unit, quota, tier intervals), `source_clearance` (append-only: approver, date, scope, reference, permitted rate, revoked flag), `connector_config` (non-secret parts; secrets referenced by name), `extraction_rule_version` (selector config; state proposed/active/retired; origin admin/llm; validation results; approver).
- `tracked_offer` (source, URL/external id, status `suggested`/`active`, `next_due_at`, own-store and own-channel flags), `offer_attributes` (versioned, with per-field provenance).
- `observation` (append-only): price_rial, stock_state, seller, raw conditions, method, extraction rule version, `observed_at`, validity, evidence object key. `fetch_attempt` (append-only): outcome, error class (incl. `blocked`), latency, http status.
- `match_version` (append-only). State: proposed/confirmed/rejected/needs_review, flags, confidence, source, actor and reason. A partial unique index enforces one current match per offer. `outlier_confirmation` (append-only): observation id, actor, reason.
- `recommendation` (append-only). Fields: outcome, suggested_price, floor, ceiling, market_ref, qualifying_count, median, reason_code, flags (`undercut_lost`), excluded outliers, explanation, input references (`observation_ids[]`, `match_version_ids[]`, `outlier_confirmation_ids[]`, `cost_record_id`, `rule_version_id`), `engine_version`, `superseded_by`. The flag `inputs_purged` is derived from the retention purge log, so rows are never updated.
- `decision` (append-only). Fields: type, reason, applied_price, override flag, `supersedes_decision_id`. `override_review` (append-only): decision id, approve/reject/self_approved, admin actor, reason.
- `decision_outcome` (append-only). One row per reached stage: `reported_done`, `observed_on_site`, `reflected_in_channel`, `verification_overdue`, each with time, actor or evidence observation id. The current outcome state is derived from these rows and from `override_review`, so `decision` is never updated.
- `audit_event` (append-only; the app role has INSERT/SELECT only, with no UPDATE/DELETE grant), `outbox_events`, `processed_events`, `qualification_run`, `match_audit_sample`, `review_session` (open/close timestamps for review-time KPI).

Money is stored as `BIGINT` Rial and all ratios as integer basis points. Arithmetic uses Python `int`/`Decimal` with explicit `ROUND_CEILING` for floor rounding, never floats. Currency conversion happens once, at the ingestion boundary.

### D5. Connector framework (per-source isolation)

Each source implements a typed `SourceConnector` protocol:

```python
class SourceConnector(Protocol):
    method: RetrievalMethod                     # api | html | rendered_page
    async def fetch(self, target: OfferTarget, ctx: FetchContext) -> FetchResult: ...
    # FetchResult = ObservationDraft | FetchFailure(error_class, retryable, detail)
```

- Extraction tries structured data first (JSON-LD `Offer`, microdata), then the source's active `extraction_rule_version`. Selector changes are data, not code changes, where possible. A new version (admin-written or LLM-suggested) is validated against the source's stored sample pages and activated only by admin approval. There is no LLM fallback for reading prices or stock.
- Clearance gate: before every request the connector runtime checks that the source has an unrevoked `source_clearance` and that its quota does not exceed the permitted rate. A missing clearance is a hard refusal, not a retryable failure.
- Every connector has contract tests against recorded fixtures (HTML/JSON saved from the qualification run). A canary job flags structural drift when the extraction success rate drops below a threshold. This turns the PRD's "site structure change requires fixing the connector" into an alert, not a silent failure.
- `FetchFailure` never creates an `observation`. Out-of-stock is set only from an explicit positive signal on a successful fetch.
- Per-domain rate limiting uses a Redis token bucket (`quota:{source_id}`), checked before every request, including expert re-checks. Re-checks also draw from a per-user daily budget.
- Politeness: a configurable, honest User-Agent, concurrency limit per domain, and respect for the source's access terms as recorded in its clearance. No proxy rotation, identity spoofing or CAPTCHA solving, and no paid scraping/proxy services without an approved budget (Q-T4). HTTP 403/429 and challenge pages map to `blocked` (non-retryable in the window); `Retry-After` pauses the source's token bucket.
- Browser fetches run only in `worker-browser` pods. They use a fresh context per job, block images and fonts, use a hard timeout, and have no access to secrets or the database role beyond writing observations.

### D6. Scheduling

`tracked_offer.next_due_at` is the source of truth. Every 30 seconds the scheduler selects due offers (`FOR UPDATE SKIP LOCKED`, batch limit) and enqueues `fetch.requested` with idempotency key `(offer_id, window_start)`. Then it advances `next_due_at` by the tier interval for that source.

Default tier intervals: A = 15 min, B = 60 min, C = 6 h, with maximum data age A = 2 h, B = 4 h, C = 24 h (rule fields). The PRD calls its "5–15 minutes" figure an experiment target, so these are configuration, not SLAs, and will be retuned after qualification within each source's permitted rate. Retry policy: exponential backoff with jitter (base 30 s, max 3 attempts, `retryable` failures only). After that the offer waits for its next window.

### D7. Recommendation engine as a pure function

`pricing.engine.recommend(inputs: RecommendationInputs, rule: RuleVersion) -> RecommendationResult` is a pure, side-effect-free function, with `ENGINE_VERSION` bumped on any behaviour change. The orchestrating handler gathers inputs, calls the function and persists the result with its input references. Business logic is kept separate from orchestration.

Evaluation order:

1. `cost_missing` → `insufficient_data` (`missing_cost`). No VAT rate in the resolved rule → `insufficient_data` (`tax_basis_unset`).
2. Candidates = confirmed ∧ condition-equivalent ∧ in stock ∧ fresh (tier max age) ∧ approved source ∧ in the competitor set (all sellers when the set is empty).
3. Outliers: a candidate is `price_outlier` when ≥ 2 other candidates exist and its price < `median(others) × (1 − outlier_threshold)`, unless an `outlier_confirmation` exists for that observation. Qualifying = candidates − unconfirmed outliers.
4. If `|qualifying| < min_qualifying_offers`, the result is `insufficient_data`, with the reason picked by precedence: pending_review (matches or outliers) > stale_evidence > below_min_offers > no_offers.
5. `floor = ceil_to_step(effective_cost / (1 − margin − fee) × (1 + vat))`. Guard: `margin + fee < 1`, otherwise the rule is invalid and rejected when it is created.
6. `market_ref = min(qualifying prices)`.
7. If `market_ref < floor`, the result is `floor_conflict`.
8. If `|our − market_ref| ≤ tolerance`, the result is `hold`.
9. Otherwise the target is `market_ref − undercut_step`, clamped to `[floor, ceiling]` and rounded up to the step (the ceiling is used if rounding would exceed it). If the rounded price equals our price, the result is `hold` (`no_change_after_rounding`). Otherwise the result is `decrease` if the target is below our price, else `increase`; a rounded `decrease` that is not below `market_ref` carries `undercut_lost`.

Per-unit profit uses the net price: `price / (1 + vat) × (1 − fee) − effective_cost`.

Invariants are covered by property-based tests (Hypothesis): no suggested price is ever below the floor, increases never exceed the ceiling, an unconfirmed outlier never becomes `market_ref`, and outputs are deterministic.

The VAT handling (margin and fees defined on the net price) is a working assumption until the store's finance team signs off (Q-D2, Q-P3). Sign-off is a phase B entry condition; a different basis would bump `ENGINE_VERSION` and add rule fields, not change the engine's shape.

*Alternative*: a configurable rules DSL. Rejected for MVP; versioned parameters on one fixed strategy are enough, and remain auditable.

### D8. Matching pipeline

1. **Text normalization**: Arabic ي/ك → Persian ی/ک, Persian/Arabic digits → ASCII, ZWNJ handling, unit synonyms (ترابایت/TB, گیگ/GB).
2. **Rule-based extraction**: brand/model dictionaries per category, regexes for capacity, frequency, generation and warranty months.
3. **LLM extraction**, used only if required attributes are still missing.
4. **Candidate blocking** by brand + category + model family.
5. **Scoring** by weighted attribute agreement. A product-identity mismatch is fatal; a condition mismatch produces `condition_mismatch`.
6. **Optional LLM match proposal** for ambiguous candidates.
7. **State assignment**. Auto-confirm happens only on an exact MPN/GTIN match with equal conditions; everything else becomes `proposed` or `needs_review`.

Rejected pairs are remembered by `(offer_id, variant_id, attributes_hash)`.

### D9. LLM integration (bounded)

- An `LLMPort` interface has five typed operations: `extract_attributes`, `propose_match`, `rephrase_explanation`, `suggest_extraction_rule` and `suggest_offer_urls`. Each has its own versioned prompt template and Pydantic output schema. Providers are adapters selected by configuration.
- The LLM ships disabled (`LLM_ENABLED=false`) and `NullLLMAdapter` is the default: the rules-first pipeline plus human confirmation is the complete baseline behaviour. No external provider is assumed permitted (Q-T2). Anthropic Claude is a candidate adapter (structured JSON output, no tools; `claude-sonnet-5-5` for extraction, matching and suggestions, `claude-haiku-5-5` for wording), enabled only after legal, data-location and compliance review. A self-hosted open-weights adapter is the fallback, subject to a cost, security and quality evaluation.
- `suggest_extraction_rule` receives stored sample pages of one source and returns a selector config; the result is saved as a `proposed` `extraction_rule_version`, validated against the samples, and needs admin approval. `suggest_offer_urls` receives a search-results page the connector already fetched (under clearance and quota) and returns ranked candidate URLs, saved as `suggested` tracked offers for expert confirmation. The model never fetches anything itself.
- Untrusted page text is wrapped in explicit delimiters, and the system prompt declares it data only.
- An outbound payload allow-list (offer text, candidate variant public attributes, public page content from cleared sources) is enforced in the port, not by convention. A unit test asserts that cost and margin fields cannot be serialized.
- The rephrase validator extracts all numbers (Persian and ASCII digits) from both texts and requires an exact multiset match; otherwise the deterministic text is used.
- A daily token budget counter lives in Redis. When it is exceeded, the port returns `BudgetExhausted` and callers fall back as the spec requires.

### D10. API and concurrency

- REST under `/api/v1`, with all request and response bodies as Pydantic models and OpenAPI published.
- Commands that change state accept an `Idempotency-Key` header, stored for 24 h.
- Decisions carry `recommendation_id`. The handler checks `superseded_by IS NULL` under `SELECT … FOR UPDATE` and returns `409 recommendation_superseded` with the current version, which implements the stale-submission scenario.
- Below-floor override: the decision command compares the applied price with the recommendation's floor. Below it, an expert's decision is stored with `below_floor_override` and is pending; an admin's is stored with a `self_approved` `override_review`. `POST /decisions/{id}/override-review` (admin only) appends approve/reject. The `reported_done` command returns `409 override_not_approved` unless an approving review exists.
- Errors use one problem-details schema (`type`, `title`, `detail`, `correlation_id`, Persian `message_fa`).

### D11. Frontend workspace

Routes:

- `/queue`: summary cards and the queue table, with filters in search params.
- `/queue/[variantId]`: evidence detail, decision form and history.
- `/matches`: the confirmation queue, including suggested offer URLs.
- `/sources`: registry, clearance records, health, qualification, extraction rule versions and approvals (admin).
- `/catalog/imports` (admin), `/rules` (admin), `/reports`.

Persian formatting:

- `Intl.NumberFormat('fa-IR')` for amounts in Toman.
- `Intl.DateTimeFormat('fa-IR-u-ca-persian')` for Jalali dates.
- Relative time comes with the absolute value in a tooltip.
- Model names render inside `<bdi dir="ltr">`.

The review-time KPI uses `review_session` open and close calls when the detail view mounts and when the decision is submitted (or after 15 minutes idle). Accessibility: keyboard navigation through the queue, and `role="status"` for save confirmations (as in the PRD prototype).

### D12. Evidence storage

- **HTML sources**: gzipped raw HTML plus the extracted JSON.
- **Rendered pages**: also a PNG screenshot.
- Object key: `{tenant}/{source}/{offer}/{observed_at}.{ext}`.
- The UI gets evidence through short-lived presigned URLs from the API, after an RLS-checked lookup.
- Default retention is 90 days for page evidence (enforced by a bucket lifecycle rule) and indefinite for observation rows (Q-D3).
- An optional per-tenant observation retention period is enforced by a scheduled purge job that runs under a dedicated maintenance DB role (the app role has no DELETE). The job writes a purge log and an audit event with counts; recommendations whose inputs were purged are reported as `inputs_purged` and are no longer replayable.
- Data location: cost, margin and rule data stay in the deployment's own database. The hosting location (Iran, customer servers or approved operator infrastructure) is decided with Q-T1.

### D13. Observability

- Each request or event carries a correlation ID, propagated through the outbox envelope and Dramatiq message headers into logs, traces and audit events.
- Prometheus metrics: fetch outcomes by source and error class, data age histogram, queue backlog, outbox lag, recommendation outcomes, LLM tokens/latency/validation failures, and token-bucket rejections.
- Source health views read from `fetch_attempt` aggregates. Alerts fire on source success rate < 80% (1 h), any `blocked` responses, outbox lag > 5 min, and a scheduler heartbeat missing for over 2 min. Alerts go to operations; experts see in-app badges only.

### D14. Deployment

- Images: `backend` (API, scheduler and non-browser workers) and `backend-browser` (adds Playwright Chromium). Both are built on UBI or distroless-compatible bases, run as non-root with an arbitrary UID, and use a read-only root filesystem with a writable `/tmp`.
- One Helm chart with Deployments per role. Additional resources: an HPA on worker queue depth (KEDA optional), NetworkPolicies (browser workers get egress only to approved source domains via egress config and to S3; no DB access except through their role), and Secrets referenced from an external secret store.
- Alembic migrations run as a pre-upgrade Job.
- Split topology (Q-T1): collector workers may run in a separate namespace or cluster, but only where they have stable and permitted access to the sources; they are never placed to work around access restrictions. In a split deployment they reach Postgres, Redis and object storage over mutually authenticated TLS with credentials scoped to their role. The final location is decided after phase A source tests.
- Local development uses `docker compose` (Postgres, Redis, MinIO, Keycloak) plus `make` targets.

### D15. Repository layout

```
backend/            pyproject.toml, src/pricing_assistant/<modules>, tests/, alembic/
web/                Next.js app, src/, tests/ (Vitest + Playwright e2e)
deploy/helm/        chart
deploy/compose/     local stack
docs/               runbooks, connector guide, ADRs
fixtures/sources/   recorded source responses for contract tests
```

CI covers lint, type-check (mypy --strict, tsc), unit and property tests, contract tests, migration up/down check, import-linter, image build, and SBOM + vulnerability scan.

## Risks / Trade-offs

- **[Risk] Digikala/Torob access**: Torob's Shop API covers only our own shop, the store's Torob and Digikala access is unconfirmed, and no official competitor API exists. Page extraction may be blocked or may breach terms. → No source is fetched without a clearance record (Q-L1); a source without clearance is dropped, never worked around. The connector interface supports switching a source from `html` to `api` without downstream changes.
- **[Risk] Floor formula vs. tax status**: comparing VAT-inclusive prices against a floor computed on net cost understates the floor if VAT is ignored. → VAT rate is a required rule field; finance sign-off of the formula is a phase B entry condition.
- **[Risk] Site structure changes break extraction.** → Structured data comes first, selectors live in configuration, fixtures back contract tests, and drift alerts fire. A failure leaves data stale, never wrong.
- **[Risk] LLM provider availability or sanctions/residency constraints for an Iranian-market deployment.** → Provider-agnostic port, a rules-first pipeline that works with the LLM disabled, and a documented self-hosted fallback.
- **[Risk] Persian title variability lowers match accuracy below 98%.** → Human confirmation is mandatory for non-exact matches, and the accuracy metric is measured on audited samples rather than assumed. Dictionaries grow from expert corrections.
- **[Risk] Currency-unit ambiguity (Rial vs Toman) on sources.** → The currency unit is a required source-level config, and a plausibility check rejects values outside 0.2×–5× of the variant's last valid price as `suspect_unit` for review.
- **[Trade-off] Modular monolith over microservices**: less independent scaling. Accepted at pilot scale; boundaries and events keep a later split mechanical.
- **[Trade-off] Lowest-price market reference**: it is sensitive to outlier sellers. → Limited to the selected competitor set and confirmed matches, with the median shown alongside. Offers far below the median of the others are excluded until an expert confirms them. With fewer than 3 candidates the outlier check cannot run; the per-offer plausibility check (`suspect_unit`) still applies.
- **[Risk] Verification depends on own-store page observation.** → Own storefront is a required source for R07, and verification overdue returns the item to the queue.

## Migration Plan

Greenfield; there is no data migration. Rollout follows PRD phases:

1. **Phase A – access proof** (about 1–2 weeks once access is ready):
   - Entry: clearance records for each candidate source, the store platform's sample export, and a decision on hosting and network location.
   - Deploy to a staging namespace.
   - Register cleared candidate sources and import the 20-variant sample.
   - Run a qualification and have admins approve or reject sources from the report. Measure the actual site and Torob publication delay and the cost per source.
2. **Phase B – pilot** (4–8 weeks):
   - Entry: finance sign-off of the floor formula, cost items and VAT basis; profit rules configured; a one-week baseline time study per category.
   - Import the full pilot catalog (100–300 variants) and enable scheduled collection for approved sources and our own storefront.
   - Onboard experts and produce weekly pilot reports.
3. **Phase C decision**: based on the four PRD pilot targets (match accuracy, floor safety, evidence completeness, review-time reduction). Tier-A coverage and verification reliability are also reported; their thresholds are set after phase A. No automatic price application is considered before quality and floor control are proven.

**Rollback**: the system never writes to the store, so rollback is operational. Suspend sources or scale workers to zero; experts revert to the manual process. Schema migrations have tested downgrade scripts. Append-only tables are never destructively migrated during the pilot.

## Open Questions

Deferrable items that do not change specs or task structure:

- Exact tier intervals, per-source quotas, tier B/C maximum data age and the outlier threshold. These are configuration, set after qualification.
- Whether percentage fees apply to the net or the VAT-inclusive price, and whether the VAT rate differs by category. This is part of the finance sign-off (Q-D2, Q-P3); it may add rule fields.
- Observation retention beyond the pilot, following the customer's retention policy (Q-D3).
- Whether `reflected_in_channel` verification covers Torob only or more channels. This adds sources, not behaviour.
- KPI naming: the Q-K3 answer names tier-A coverage/freshness and verification reliability as the "other two" PRD KPIs, while the PRD lists floor safety and evidence completeness. This plan keeps the PRD's four and adds the two as extra KPIs; reconcile with the PRD owner.

The answers recorded in `business-questions.md` (2026-10-25) are folded into all artifacts. The customer confirmations still open are listed in the proposal's Impact section.
