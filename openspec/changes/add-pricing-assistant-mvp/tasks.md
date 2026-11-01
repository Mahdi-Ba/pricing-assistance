# Tasks

> Answers from `business-questions.md` (2026-10-25) are folded in. Tasks marked **(Q-xx)** depend on a customer confirmation that is still open or on a setting tuned after phase A; re-check them before starting.

## 1. Repository and local stack

- [x] 1.1 Create the repo layout from design D15 (`backend/`, `web/`, `deploy/helm/`, `deploy/compose/`, `docs/`, `fixtures/sources/`) with root `README.md` and `Makefile`; verify `make help` lists targets
- [x] 1.2 Scaffold `backend/` with Python 3.12, `pyproject.toml` (FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, Dramatiq[redis], httpx, selectolax, extruct, structlog, OpenTelemetry, prometheus-client, pytest, hypothesis, mypy, ruff, import-linter) and an empty module per D1; verify `make backend-check` (ruff + mypy --strict + pytest) passes
- [x] 1.3 Scaffold `web/` with Next.js (App Router, TypeScript strict), Tailwind, TanStack Query, Zod, Vitest, Playwright and the Vazirmatn font; verify `npm run lint && npm run typecheck && npm test` pass
- [x] 1.4 Add `deploy/compose/docker-compose.yml` with PostgreSQL 16, Redis 7, MinIO and Keycloak (realm import with `admin` and `expert` test users and a `tenant_id` claim mapper); verify `make up` starts all services healthy and a test user can obtain a token
- [x] 1.5 Add an import-linter contract allowing cross-module imports only via `api.py` and `events.py`; verify a deliberate violation fails `make backend-check`

## 2. Platform foundations

- [x] 2.1 Implement typed settings (Pydantic Settings) with secrets read from env or mounted files and never logged; verify with a unit test that the settings `repr` and log output redact secret fields
- [x] 2.2 Create the Alembic baseline with `tenant` and an RLS helper migration (non-owner app role, `app.tenant_id` setting, policy template); verify `alembic upgrade head && alembic downgrade base` succeed in CI
- [x] 2.3 Implement the DB session factory that sets `app.tenant_id` per transaction from the principal or event envelope; verify an integration test that a session for tenant T1 cannot read a T2 row even with a raw `SELECT`
- [x] 2.4 Implement OIDC JWT validation (JWKS cache, issuer, audience, expiry) and a `Principal` dependency with roles and tenant; verify that tests for missing, expired and wrong-audience tokens return 401
- [x] 2.5 Implement role-based authorization guards (`admin`, `expert`) with audit of denied attempts; verify that the expert-calls-admin-endpoint test returns 403 and writes an audit event
- [x] 2.6 Implement the append-only `audit_event` table (INSERT/SELECT grants only) and the `audit.record()` API; verify with a DB test that UPDATE/DELETE as the app role fails
- [x] 2.7 Implement the event envelope model, `outbox_events` and `processed_events` tables, the outbox relay (scheduler role) and an idempotent consumer decorator for Dramatiq actors; verify integration tests for duplicate-delivery idempotency and rollback-no-publish
- [x] 2.8 Implement scheduler leader election via Postgres advisory lock and a heartbeat metric; verify with a test that two scheduler instances result in one active leader
- [x] 2.9 Wire structlog JSON logging, OpenTelemetry tracing and correlation-ID propagation (HTTP header → outbox envelope → Dramatiq message → logs/audit); verify with a test that one request's correlation ID appears in the API log, worker log and audit event
- [x] 2.10 Implement problem-details error responses (`type`, `title`, `detail`, `correlation_id`, `message_fa`) and the `Idempotency-Key` middleware for commands; verify with API tests that a replayed command returns the original response
- [x] 2.11 Document local setup and architecture overview in `docs/architecture.md` and `docs/local-dev.md`; verify a fresh clone can follow the documented steps to `make up && make test`

## 3. Catalog management

- [x] 3.1 Create migrations for `product`, `variant` (MPN/GTIN, colour/edition, importance tier, `cost_status`, current price), `cost_record` (versioned; import ID, uploader, previous value, hold state) and `catalog_import`; verify migration up/down tests
- [x] 3.2 Implement currency conversion at the boundary (Toman/Rial → integer Rial, Persian/Arabic digit and separator parsing); verify unit tests including «۸٬۴۰۰٬۰۰۰», `8,400,000` and missing unit
- [x] 3.3 Publish the CSV/XLSX column template and implement header validation that rejects the whole file on a missing required column; verify the template-mismatch scenario test
- [x] 3.4 Implement row validation with Persian error messages (row, column, message), and partial import of valid rows; verify the mixed-rows scenario (rows 4 and 7 reported, 8 imported)
- [x] 3.5 Make imports idempotent by content hash and upsert key (SKU); verify that re-uploading an identical file reports all rows as unchanged
- [x] 3.6 Enforce upload size and type limits before parsing; verify the oversized-upload test is rejected without parsing
- [x] 3.7 Implement effective-cost configuration (fixed per-unit components such as freight, insurance, customs, warehousing, packaging; purchase cost excludes recoverable VAT) and `cost_missing` status; verify the scenarios "fixed components added" and "cost absent" **(Q-D2)**
- [x] 3.8 Implement versioned `profit_rule_version` (default/category/variant scope, margin, fees, VAT rate required at default scope, ceiling, undercut step, hold tolerance, max data age per tier, rounding step, outlier threshold, min qualifying offers, competitor set per source) with validation `margin + fee < 1`, the initial values from the catalog spec, and most-specific-scope resolution; verify the scenarios "category override", "rule edit creates version" and "VAT rate required" **(Q-P2, Q-P3, Q-S5)**
- [x] 3.9 Expose admin API endpoints for imports (upload, status, report), rules and cost components, emitting `catalog.cost.changed` / `rule.version.created` events and audit records; verify API tests for each event and audit entry
- [x] 3.10 Document the import template and rule semantics in `docs/catalog-import.md`; verify that the example file in the doc imports successfully in a test
- [x] 3.11 Implement the cost plausibility hold (new cost >5× or <0.2× previous → `suspect_unit`, previous cost stays in force) and the admin confirm command with audit and `catalog.cost.changed` on confirmation; verify the scenarios "Toman entered as Rial" and "cost history" **(Q-D5, Q-D6)**

## 4. Source registry and connector framework

- [x] 4.1 Create migrations for `source` (method, currency unit, quota, tier intervals, lifecycle status), append-only `source_clearance` (approver, date, scope, reference, permitted rate, revoked), `connector_config`, `extraction_rule_version` and `tracked_offer` (status `suggested`/`active`, own-store and own-channel flags, `next_due_at`); verify migration tests **(Q-L1)**
- [x] 4.2 Implement source lifecycle transitions with rules (only `approved` feeds pricing; `under_evaluation` and `approved` require an unrevoked clearance; status changes need a reason; quota ≤ permitted rate; revoking clearance suspends) and audit; verify the scenarios "candidate excluded", "source suspended", "quota above permitted rate" and "clearance revoked" **(Q-L1)**
- [x] 4.3 Define the `SourceConnector` protocol, `OfferTarget`, `FetchContext`, `ObservationDraft` and `FetchFailure` (error classes, `retryable`); verify with mypy and a protocol conformance test using a fake connector
- [x] 4.4 Implement the structured-data-first extractor (JSON-LD/microdata `Offer`) and selector extraction driven by the source's active `extraction_rule_version`, recording the rule version on each observation; verify fixture-based unit tests for price, stock and seller extraction
- [x] 4.5 Implement the Redis token-bucket rate limiter per source (with `Retry-After` pause) plus a per-user re-check budget (default 50/day, admin-configurable); verify concurrency tests (60 rpm limit under 200 due offers yields ≤60 rpm with no drops) **(Q-W3)**
- [x] 4.6 Implement the plain HTTP fetcher (httpx; timeouts, configured honest User-Agent, per-domain concurrency, no proxy rotation) with `blocked` classification for HTTP 403/429 and challenge pages; verify a test that an `html` source never starts a browser and the "blocked response" scenario (no retry in window, no alternative route)
- [x] 4.7 Implement the Playwright fetcher for `rendered_page` sources (fresh context, blocked media, hard timeout, screenshot); verify with an integration test against a local dynamic test page
- [x] 4.8 Implement evidence storage to S3 (gzipped HTML, extracted JSON, screenshot) with the key scheme from D12 and presigned read URLs behind an RLS lookup; verify an integration test with MinIO, including a cross-tenant 404
- [x] 4.9 Add admin API endpoints for sources, connector configs (secrets write-only, shown as set/unset) and tracked offers; verify an API test that secret values are never returned
- [x] 4.10 Document how to add a connector in `docs/connectors.md` (protocol, fixtures, contract tests, selector config, clearance prerequisites, no-circumvention rules); verify by following it to add the test fixture connector used in 4.4
- [x] 4.11 Implement the clearance gate in the connector runtime: every scheduled fetch, re-check and qualification fetch is refused without an unrevoked clearance; verify the "source without clearance" scenario sends no request **(Q-L1)**
- [x] 4.12 Implement the extraction rule version workflow (propose → validate against stored sample pages → admin approve → active; previous version retired) with audit; verify the "suggested rule awaits approval" and "extraction fails without LLM fallback" scenarios

## 5. Market data collection

- [x] 5.1 Create migrations for append-only `observation` and `fetch_attempt`; verify with a DB test that the app role cannot UPDATE/DELETE observations
- [x] 5.2 Implement the scheduler tick (`FOR UPDATE SKIP LOCKED` on due offers, `fetch.requested` with key `(offer_id, window_start)`, advance `next_due_at` by tier interval); verify the duplicate-trigger scenario executes exactly once **(Q-S5)**
- [x] 5.3 Implement collection actors (`worker-collect`, `worker-browser`) that write an observation or a fetch attempt, never an out-of-stock on failure, with exponential backoff and jitter (3 attempts, retryable only); verify the scenarios "parse failure", "explicit out-of-stock" and "transient error recovers"
- [x] 5.4 Implement a plausibility check that flags `suspect_unit` for prices outside 0.2×–5× of the last valid price; verify a unit test with a Rial/Toman mix-up
- [x] 5.5 Implement freshness evaluation against the applicable rule's max data age for the variant's tier, exposing a stale/failed label (`قدیمی / دریافت ناموفق`); verify the scenarios "observation ages out" and "lower tier has its own limit" **(Q-S5)**
- [x] 5.6 Implement own-store and own-channel tracked offers and flag their observations separately; verify the "own page tracked" scenario
- [x] 5.7 Implement the on-demand re-check command (quota and budget check, refusal with next-slot time, status tracking); verify the "re-check refused by quota" scenario sends no request
- [x] 5.8 Implement source health aggregates (success rate, error breakdown, data age median/max, request count, cost estimate), Prometheus metrics and alert rules from D13; verify a test that the 24 h health view matches seeded fetch attempts
- [x] 5.9 Implement a source-isolation test: one source failing on every request does not delay other sources' scheduled fetches or recommendation processing; verify that the integration test passes
- [x] 5.10 Implement an injected-text fixture test: a title containing instructions is stored as data and causes no state change; verify the test passes
- [x] 5.11 Implement data retention: evidence lifecycle display ("snapshot expired"), optional per-tenant observation retention, and the purge job under a dedicated maintenance DB role with purge log, audit event and `inputs_purged` reporting; verify the scenarios "evidence expires" and "history retention configured", and that the app role cannot DELETE observations **(Q-D3)**

## 6. Source qualification (phase A) and initial connectors

- [x] 6.1 Implement `qualification_run` (variant sample, default 20; cleared candidate sources only) and a report (match rate, extraction success, freshness, limits hit, cost per source); verify the "qualification completed" scenario with fake connectors
- [x] 6.2 Implement the admin approve/reject action from a qualification report with reason and clearance reference; verify an audit event and status change test **(Q-L1)**
- [x] 6.3 Implement the Torob Shop API connector for our own shop's data (read-only scopes), with recorded-fixture contract tests; verify that the contract tests pass and that no write scope exists in the config schema. Live use only once the store confirms Shop API access and credentials **(Q-S2)**
- [x] 6.4 Implement candidate page connectors for Torob product pages and Digikala product pages (structured data + selector configs), with recorded fixtures; verify the contract tests pass (live use gated on clearance; Digikala is dropped from automated collection if clearance is not obtained) **(Q-L1, Q-S2, Q-S3)**
- [x] 6.5 Implement connectors for the specialist-shop candidates Lion Computer (`lioncomputer.com`) and Meghdad IT (`meghdadit.com`), extracting only the shop's own offers (no third-party sellers), with fixtures; verify the contract tests pass (live use gated on clearance) **(Q-L1, Q-S1)**
- [x] 6.6 Implement the own-storefront page connector for outcome verification; verify the contract test against a fixture of our product page **(Q-D1)**
- [ ] 6.7 Write the phase A runbook (`docs/runbooks/qualification.md`): clearance records, sample selection, run, report review, approval, measuring site and Torob publication delay; verify a dry run on staging produces a report
- [x] 6.8 Implement tracking of our own Torob listing as an own-channel source for `reflected_in_channel`; verify a contract test that channel observations are flagged own-channel **(Q-S2)**

## 7. Product matching

- [x] 7.1 Create migrations for versioned `offer_attributes` (per-field provenance) and append-only `match_version` with a partial unique index for the current match per offer; verify migration and constraint tests
- [x] 7.2 Implement Persian/English text normalization (ی/ک, digits, ZWNJ, unit synonyms); verify a unit test table with the PRD examples
- [x] 7.3 Implement rule-based attribute extraction (brand/model dictionaries per category; MPN/GTIN; capacity, generation, frequency, colour/edition and warranty regexes; new/used/open-box; cash/instalment); verify the "title normalized" scenario and a golden-file test set of ≥100 titles
- [x] 7.4 Implement candidate blocking and weighted scoring with fatal identity mismatch and `condition_mismatch` flags; verify the "different warranty" scenario yields `needs_review`
- [x] 7.5 Implement state assignment (auto-confirm only on a valid, equal MPN or check-digit-valid GTIN with identical model, part number, capacity, colour/edition, warranty and condition; otherwise `proposed`/`needs_review`) and audit; verify the scenarios "exact identifier match", "invalid GTIN" and "LLM-proposed match not auto-confirmed" **(Q-D4)**
- [x] 7.6 Implement expert match commands (confirm; reason required for reject, re-assign and equivalence despite `condition_mismatch`) creating new versions and emitting `match.changed`; verify the scenarios "expert rejects match", "equivalence confirmed" and "confirmed match corrected"
- [x] 7.7 Implement rejected-pair memory keyed by `(offer_id, variant_id, attributes_hash)`; verify the "re-run after rejection" scenario
- [x] 7.8 Wire matching as a `worker-process` consumer of `offer.attributes.updated` / `observation.recorded`; verify an integration test from a new observation to a proposed match

## 8. LLM assistance (bounded)

- [x] 8.1 Define `LLMPort` with `extract_attributes`, `propose_match`, `rephrase_explanation`, `suggest_extraction_rule` and `suggest_offer_urls`; versioned prompt templates; Pydantic output schemas; and `NullLLMAdapter` as the default (`LLM_ENABLED=false`); verify that the full pipeline tests pass with the null adapter and the "no provider cleared" scenario **(Q-T2)**
- [x] 8.2 Implement an outbound payload allow-list in the port (offer text, candidate public attributes, public page content from cleared sources only); verify a unit test that cost, margin and rule fields cannot be serialized into a request
- [x] 8.3 Implement untrusted-content delimiting in prompts, with tool use disabled; verify the prompt-injection fixture still yields `proposed` and no action
- [x] 8.4 Implement strict schema validation with discard-and-fallback; verify the "malformed extraction" scenario
- [x] 8.5 Implement the rephrase number-preservation validator (Persian and ASCII digits, multiset equality); verify the "number altered" scenario falls back to deterministic text
- [x] 8.6 Implement call logging (task, model, template version, tokens, latency, validation result, correlation ID) and a Redis daily budget with `BudgetExhausted` fallback; verify the "budget exhausted" scenario
- [x] 8.7 Implement the Anthropic adapter as a candidate provider (structured output, no tools; models from config: `claude-sonnet-5-5` for extract/match/suggestions, `claude-haiku-5-5` for rephrase), enabled only after compliance sign-off; verify adapter contract tests with recorded responses **(Q-T2)**
- [x] 8.8 Document the LLM role, data boundaries, compliance gate and how to switch providers in `docs/llm.md`; verify the provider-switch scenario with the null and recorded adapters
- [x] 8.9 Implement `suggest_extraction_rule` over a source's stored sample pages, saving the result as a `proposed` extraction rule version through 4.12; verify the "extraction rule suggestion" scenario with the recorded adapter **(Q-S6, Q-T2)**
- [x] 8.10 Implement `suggest_offer_urls` over a search-results page fetched by the connector (under clearance and quota), saving results as `suggested` tracked offers; verify the "offer URL suggestion" scenario and that no scheduled fetch is created before confirmation **(Q-S6, Q-T2)**

## 9. Price recommendation engine

- [x] 9.1 Create migrations for append-only `recommendation` (outcome, prices, floor/ceiling, market reference, qualifying count, median, reason code, flags, excluded outliers, explanation, input reference arrays, `engine_version`, `superseded_by`) and `outlier_confirmation`; verify migration tests
- [x] 9.2 Implement the pure `recommend()` function following D7, with integer Rial and basis points, VAT-inclusive floor, outlier exclusion, minimum qualifying offers and price rounding; verify unit tests for every spec scenario (decrease 85,500,000; increase 85,500,000; floor 100,000,000; floor with fee 105,882,353; VAT floor 110,000,000; tax basis unset; market below floor; ceiling cap; hold within tolerance; stale-only; out-of-stock excluded; seller outside competitor set; outlier excluded; rounded up 85,500,000; undercut lost 86,000,000; per-unit profit 10,500,000) **(Q-D2, Q-P3)**
- [x] 9.3 Add Hypothesis property tests: suggested price ≥ floor; increase ≤ ceiling; unconfirmed outlier never sets the market reference; suggested price is a multiple of the rounding step or equals the ceiling; deterministic output; no suggestion when outcome ∉ {increase, decrease}; verify 10k examples pass in CI
- [x] 9.4 Implement the deterministic Persian explanation templates per reason code and flag (competitor, price, observed time, floor, `undercut_lost`, excluded outliers); verify snapshot tests per reason code and flag
- [x] 9.5 Implement the orchestration handler: gather inputs (qualifying offers per D7), call the engine, persist with references, supersede the previous recommendation, debounce per variant (5 s); verify an integration test that a burst of 10 observations yields one new recommendation
- [x] 9.6 Implement recomputation triggers on `observation.recorded`, `match.changed`, `outlier.confirmed`, `catalog.cost.changed` and `rule.version.created`; verify the "new observation arrives" scenario
- [x] 9.7 Implement a replay endpoint/command that recomputes a stored recommendation from its references and compares (reporting `inputs_purged` when inputs were purged); verify the "replay" scenario returns identical output
- [x] 9.8 Implement the expert outlier-confirmation command (per observation, reason required, audit, emits `outlier.confirmed`); verify the "outlier confirmed by expert" scenario

## 10. Pricing decisions and outcome tracking

- [x] 10.1 Create migrations for append-only `decision` (type, reason, applied price, override flag, supersedes link), `override_review` and `decision_outcome`; verify migration and no-UPDATE tests
- [x] 10.2 Implement the record-decision command with mandatory reason, an applied price for accept types, and the `SELECT … FOR UPDATE` superseded check returning 409; verify the scenarios "decision without reason", "accept recorded" and "stale submission"
- [x] 10.3 Implement the admin-approved below-floor override: expert decision stored `override_pending` with reason; admin-only `override-review` command (approve/reject with reason); `self_approved` for admin submitters; `reported_done` refused with `409 override_not_approved` until approved; audit for each step; verify the scenarios "modified price below floor", "report done before approval", "admin approves override", "admin rejects override" and "admin's own override" **(Q-B3)**
- [x] 10.4 Implement decision correction as a superseding decision; verify the "correction" scenario keeps both visible
- [x] 10.5 Implement the `reported_done` command and own-store/channel observation matching for `observed_on_site` / `reflected_in_channel`, recording site and channel delays separately; verify the scenarios "reported but not yet observed", "observed on site" and "channel lag"
- [x] 10.6 Implement the verification-window timer in the scheduler and return to queue as `verification_overdue`; verify the "overdue" scenario with a 2 h window **(Q-W2)**
- [x] 10.7 Add an architecture test that no connector config schema accepts write scopes and no API route performs external price writes (route inventory check); verify the "integration scope check" scenario in CI
- [x] 10.8 Implement the variant history query (recommendations, decisions, applied prices, outcomes in order); verify the "history view" scenario

## 11. Workspace query API

- [x] 11.1 Implement the live queue read model and endpoint with priority score (tier, outcome weight, profit impact, age), exposed score inputs and alert badges for source failures and floor conflicts; verify the "tier A floor conflict on top" scenario
- [x] 11.2 Implement queue filters (category, tier, outcome, status incl. awaiting override approval and verification overdue, source health flag) and cursor pagination; verify a filter test for each dimension
- [x] 11.3 Implement the summary-card endpoint whose counts use the same filter definitions as the queue, including the admin-only overrides-awaiting-approval card; verify that each card count equals the filtered queue length
- [x] 11.4 Implement the item detail endpoint (recommendation, explanation, floor/ceiling, evidence rows with match state, flags, non-qualification reason, freshness and presigned source/evidence links); verify the "evidence row content" scenario
- [x] 11.5 Implement the match confirmation queue endpoint with side-by-side attributes and diff markers, plus suggested offer URLs with confirm/dismiss; verify the scenarios "side-by-side compare" and "confirm suggested URL"
- [x] 11.6 Implement `review_session` open/close endpoints (15 min idle close); verify a timing test
- [x] 11.7 Generate the OpenAPI schema in CI and fail on uncommitted drift; verify `make openapi-check`

## 12. Web workspace (Persian RTL)

- [x] 12.1 Implement the Auth.js BFF with Keycloak (httpOnly server session, no token in browser JS) and role-aware navigation; verify a Playwright e2e test that an expert cannot see admin pages and that `document.cookie` contains no access token **(Q-T3)**
- [x] 12.2 Generate the typed API client from OpenAPI, plus Zod validation of responses; verify `npm run typecheck` and a contract test against a mock server
- [x] 12.3 Implement RTL layout, Persian number/currency formatting (Toman), Jalali dates with absolute-time tooltips, and `<bdi dir="ltr">` model names; verify component tests including «Kingston DDR5 · 32GB / 5600»
- [x] 12.4 Implement `/queue` with summary cards linked to filtered views, a table matching the PRD columns, URL-synced filters and keyboard navigation; verify the e2e scenarios "card drill-down" and "filter by status"
- [x] 12.5 Implement `/queue/[variantId]` detail with evidence table, match and outlier actions (reject/confirm/confirm outlier/re-check), decision form (reason required, applied price, below-floor override request), admin approve/reject of pending overrides, and the post-save notices «تصمیم ثبت شد؛ هیچ قیمتی در فروشگاه تغییر نکرد» and the pending-approval notice; verify the e2e scenarios "reject from evidence", "confirm outlier from evidence", "notice after decision", "notice for pending override" and "stale submission (409) shows new version"
- [x] 12.6 Implement `/matches` confirmation queue with side-by-side diff and suggested URLs; verify the e2e test confirm/reject flow and suggested-URL confirmation
- [x] 12.7 Implement admin pages: `/catalog/imports` (upload, row error report, `suspect_unit` cost confirmation), `/rules` (versioned editor incl. VAT, per-tier data age, outlier and rounding fields), `/sources` (registry, clearance records, health, qualification report, approve/reject, extraction rule versions and approval); verify e2e tests for an import with errors, a source clearance plus approval, and an extraction rule approval
- [x] 12.8 Implement variant history and outcome-state display (override pending / approved / rejected; reported / observed on site / reflected in channel / overdue); verify a component test for each state
- [x] 12.9 Run an accessibility check (axe) on queue and detail pages; verify no serious or critical violations

## 13. Performance reporting

- [x] 13.1 Implement the monthly match audit sample (200 or all, stratified by category, source and confidence band; admin marks correct/incorrect) and overall and per-stratum accuracy; verify the scenarios "accuracy computed" (98.5% on 197/200) and "stratified sample" **(Q-K2)**
- [x] 13.2 Implement floor-safety (incl. overrides with requester, approver or `self_approved`, and reasons) and evidence-completeness metrics; verify report scenarios with seeded data
- [x] 13.3 Implement review-time median/p90 per category, per-category baseline entry and the category-mix-weighted reduction, with a low-sample label under 30 decisions; verify the scenarios "reduction against baseline" (58%), "category mix" (58%) and "small sample" **(Q-K1)**
- [x] 13.4 Implement operational KPIs (source success, data age, cost per source, LLM usage/cost, backlog, recommendation-to-decision time) and coverage/verification KPIs (tier-A coverage and data age, verification reliability, site vs. channel delay) in a weekly report, with target vs. measured labelling and unset targets shown as such; verify the scenarios "weekly report" and "verification reliability" **(Q-K3)**
- [x] 13.5 Implement the `/reports` page; verify an e2e test that the report renders with seeded data

## 14. Deployment and CI

- [x] 14.1 Build `backend` and `backend-browser` images (non-root, arbitrary UID, read-only root FS, writable `/tmp`); verify the containers start with `--user 1000680000` and `--read-only`
- [ ] 14.2 Create the Helm chart: Deployments per role, Alembic pre-upgrade Job, HPA on queue depth, probes, resource limits, NetworkPolicies (browser workers: egress only to approved domains and S3), external-secret references; verify with `helm lint`, `helm template` and kubeconform, and that it installs on an OpenShift-compatible test cluster with the restricted SCC **(Q-T1)**
- [ ] 14.3 Support deploying collector workers in a separate namespace or cluster with their own egress and mTLS connections to Postgres, Redis and object storage (D14 / Q-T1) through chart values; verify with `helm template` for split topology **(Q-T1)**
- [ ] 14.4 Set up the CI pipeline: lint, type-check, unit/property/contract tests, migration up/down, import-linter, OpenAPI drift, image build, SBOM and vulnerability scan; verify the pipeline is green on main
- [ ] 14.5 Write operations runbooks (`docs/runbooks/`): source failure, source blocked (no circumvention; suspend or contact the source), clearance revocation, structural drift, outbox lag, scheduler down, key rotation, retention purge, rollback by suspending sources; verify each runbook's commands against staging

## 15. End-to-end integration verification

- [ ] 15.1 Run a staging end-to-end test with recorded-fixture sources: import catalog → schedule fetch → observation → match confirmation → recommendation → expert decision → own-store observation → `observed_on_site`; verify that all states and audit events are present with one correlation chain
- [ ] 15.2 Run a failure-mode suite on staging: source down, source blocked, missing clearance, layout change, stale data, quota exhaustion, price outlier, suspect cost unit, LLM disabled, duplicate events; verify that each produces the spec-defined behaviour and no recommendation below the floor
- [ ] 15.3 Run a tenant-isolation penetration check across the API and evidence URLs with two seeded tenants; verify zero cross-tenant reads
- [ ] 15.4 Run the phase A qualification on staging with the cleared candidate sources (from Torob pages, Digikala pages, Lion Computer, Meghdad IT) and the 20-variant sample; verify that the qualification report is produced and source approval decisions are recorded **(Q-L1, Q-S1–Q-S3)**
- [x] 15.5 Write the phase gate checklist (`docs/runbooks/phase-gates.md`): phase A entry (per-source clearance, store platform export, hosting decision), phase B entry (finance sign-off of floor formula and VAT basis, rules configured, per-category baseline study), phase C decision criteria; verify each item links to its business question and to the evidence that closes it **(Q-K3)**
