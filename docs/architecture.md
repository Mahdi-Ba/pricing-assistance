# Architecture

The pricing assistant is a decision-support system: it collects market prices from cleared sources, matches them to the store's variants, computes deterministic floor-safe recommendations and records the expert's decisions. **It never writes prices to a store or channel.**

Requirements and decisions live in `openspec/changes/add-pricing-assistant-mvp/` (`specs/`, `design.md`). This page summarises how the code implements them.

## Processes

One backend image runs in several roles (design D1):

| Role | Entrypoint | Responsibility |
|---|---|---|
| `api` | `uvicorn --factory pricing_assistant.app:create_app` | REST API under `/api/v1`, authentication, commands, queries |
| `scheduler` | `python -m pricing_assistant.scheduler` | Leader-elected periodic jobs: outbox relay, due fetches, verification timers |
| `worker-process` | `dramatiq pricing_assistant.workers --queues process` | Normalisation, matching, recommendation, explanation wording, reporting consumers |
| `worker-collect` | `dramatiq pricing_assistant.workers --queues collect` | API and HTML fetches, search pages for offer-URL suggestions |
| `worker-browser` | same, `--queues browser`, browser image | Rendered-page fetches only |
| `web` | `next start` | Persian RTL workspace; Auth.js backend-for-frontend |

Several scheduler replicas may run. Only the one holding a PostgreSQL advisory lock (`core/scheduler.py`) runs jobs; if its session dies, a standby takes over.

## Backend modules

`backend/src/pricing_assistant/` contains one package per capability: `catalog`, `sources`, `collection`, `matching`, `pricing`, `decisions`, `workspace`, `llm`, `iam`, `audit`, `reporting`. Plus `core`, the shared kernel (settings, persistence, events, errors, logging, tracing).

- A module may import another module only through its `api.py` (public interface) or `events.py` (event payloads). `import-linter` enforces this in `make backend-lint`.
- `core` must not import any domain module.
- Composition roots (`app.py`, `workers.py`, `scheduler.py`, `wiring.py`) wire module internals together and are the only exceptions.

## Event flow

State changes write the domain row and an `outbox_event` row in the same transaction (`core/events.publish`). The scheduler's relay (`core/outbox.OutboxRelay`) sends committed events to Dramatiq and marks them dispatched. Delivery is at-least-once.

Consumers are wrapped by `core/consumer.idempotent_consumer`. They record `(consumer, event_id)` in `processed_event` in the same transaction as their own writes, so a redelivered event is skipped. Consumer wiring is declared once in `wiring.consumer_specs()` and shared by the worker (actors) and the scheduler (routing).

```
command ─▶ domain row + outbox_event (one transaction)
scheduler relay ─▶ Dramatiq queue ─▶ idempotent consumer ─▶ domain rows + further events
```

Event envelope: `event_id` (UUIDv7), `type`, `version`, `tenant_id`, `occurred_at`, `correlation_id`, `causation_id`, `payload`.

## Tenancy and data access

- Every business table has `tenant_id` and a PostgreSQL row-level security policy (`core/migration_helpers.enable_tenant_rls`). The policy is forced, so it also applies to the table owner.
- `Database.tenant_session(tenant_id)` sets `app.tenant_id` at transaction start. Without it, queries see no rows.
- Background processes enumerate tenants through the `SECURITY DEFINER` function `pa_active_tenant_ids()` and then work per tenant.
- Database roles (created by `deploy/compose/postgres/init.sh`, mirrored in deployment):

  | Role | Use | Notes |
  |---|---|---|
  | `pa_owner` | migrations | owns the schema |
  | `pa_app` | API and workers | no `BYPASSRLS`, explicit per-table grants; append-only tables (`audit_event`, `processed_event`, …) get `SELECT, INSERT` only |
  | `pa_maintenance` | retention purge jobs | — |

- Money is stored as integer Rial (`BIGINT`) and ratios as integer basis points. There is no float arithmetic.

## Security

- **Authentication:** OIDC access tokens are validated against the IdP's JWKS (`iam/oidc.py`): signature, issuer, audience and expiry. The `tenant_id` and `roles` claims become a `Principal`.
- **Browser sessions:** the browser never holds an access token; the web app is a backend-for-frontend.
- **Roles:** `admin` and `expert`. Guards (`iam/guards.require_roles`) return 403 and write an `authorization.denied` audit event.
- **Audit:** an append-only audit log (`audit_event`) records every state-changing action with actor, target, before/after summary, reason and correlation ID.
- **Secrets:** secrets are `SecretStr` settings, read from the environment or mounted files (`PA_SECRETS_DIR`). The log processor redacts sensitive keys.
- **Idempotency:** commands accept `Idempotency-Key` (`core/idempotency.IdempotentRoute`); replays return the stored response for 24 h.

## Errors

All errors are RFC 9457 problem details (`application/problem+json`) with `type`, `title`, `status`, `detail`, `correlation_id` and a Persian `message_fa`. Internal details never leave the server.

## Observability

- **Correlation:** `X-Correlation-ID` is adopted or created per request (`core/http.CorrelationMiddleware`). It is carried in the event envelope into workers and stored on audit events.
- **Logs:** structured JSON via structlog, with `correlation_id`, `trace_id` and `span_id`.
- **Tracing:** OpenTelemetry, with OTLP export when `PA_OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- **Metrics:** Prometheus at `/metrics`. Includes scheduler heartbeat and leadership, job runs, HTTP latency and outbox lag.

Language-model use is optional, bounded and off by default; see [llm.md](llm.md).
