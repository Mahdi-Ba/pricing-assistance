# Local development

## Prerequisites

- Docker with Compose v2
- [uv](https://docs.astral.sh/uv/) ≥ 0.9 (installs Python 3.12 automatically)
- Node.js ≥ 22 with npm
- GNU make

## First run

```bash
make up                         # Postgres, Redis, MinIO, Keycloak; waits until healthy
make backend-install            # uv sync into backend/.venv
make web-install                # npm ci in web/
make migrate                    # apply migrations to the development database
make test                       # lint, type-check, unit and integration tests, web checks
```

`make help` lists all targets. `make reset` deletes the stack's volumes for a clean start.

## Local stack

Ports avoid the defaults so the stack can run beside local Postgres or Redis installations. Override any value in `deploy/compose/.env` (copy `.env.example`).

| Service | Host port | Notes |
|---|---|---|
| PostgreSQL 16 | 55432 | databases `pricing` (dev) and `pricing_test` (integration tests); roles `pa_owner`, `pa_app`, `pa_maintenance` |
| Redis 7 | 56390 | Dramatiq broker, rate limits; tests use DB 15 |
| MinIO | 59000 (API), 59001 (console) | evidence snapshots |
| Keycloak 26 | 58080 | realm `pricing-assistance` |

All credentials in the compose file are development-only defaults.

### Development users (realm `pricing-assistance`)

| User | Password | Role | Tenant |
|---|---|---|---|
| `pilot-admin` | `dev-password-1` | admin | `0192f0a0-0000-7000-8000-000000000001` |
| `pilot-expert` | `dev-password-1` | expert | `0192f0a0-0000-7000-8000-000000000001` |
| `sandbox-expert` | `dev-password-1` | expert | `0192f0a0-0000-7000-8000-000000000002` |

Get an access token for API calls (the password grant is enabled only in this development realm):

```bash
curl -s -X POST http://localhost:58080/realms/pricing-assistance/protocol/openid-connect/token \
  -d grant_type=password -d client_id=pricing-web -d client_secret=pricing-web-dev-secret \
  -d username=pilot-expert -d password=dev-password-1 | jq -r .access_token
```

## Running the processes

From `backend/`:

```bash
uv run uvicorn --factory pricing_assistant.app:create_app --reload --port 8000
uv run python -m pricing_assistant.scheduler
uv run dramatiq pricing_assistant.workers --queues process collect
```

From `web/`: copy `.env.example` to `.env.local`, set `AUTH_SECRET` (for example `openssl rand -base64 33`), then `npm run dev` (http://localhost:3000). Sign in with one of the development users above.

The web app is a backend-for-frontend: the browser holds only Auth.js's encrypted, httpOnly session cookie. Keycloak tokens stay on the server, and the browser calls the API through the same-origin proxy `/api/backend/api/v1/...`, which adds the bearer token and refuses cross-origin writes.

### Demo data

To click through the app with realistic data, use the e2e database: seed it with `cd backend && uv run python -m tests.support.e2e_seed reset` (with the `PA_*` variables from `web/tests/e2e/stack.ts`), then start the API, scheduler and worker with those variables. Run the worker with `--queues process` only. The demo's sources and clearances are test fixtures, not real permissions, so the demo must not collect. Its URLs use the reserved `shop.pricing-demo.test` domain, which never resolves, as a second safeguard. Use the `collect` queue only with sources that have a real recorded clearance.

To expose the scheduler's or a worker's Prometheus metrics locally, set `PA_METRICS_PORT` (for example `9101`) for that process. Run workers with `--processes 1` when you do, so the port is used once.

Settings are environment variables prefixed with `PA_` (see `backend/src/pricing_assistant/core/settings.py`). The defaults point at the local stack.

## Tests

| Command | Scope |
|---|---|
| `make backend-check` | ruff, import contracts, mypy `--strict`, unit tests (no services needed) |
| `make backend-test-integration` | tests marked `integration`; migrate `pricing_test` from scratch and need `make up` |
| `make web-check` | ESLint, TypeScript, Vitest |
| `make e2e` | browser end-to-end tests of the whole stack (see below) |

Rendered-page tests (`test_browser_fetcher.py`) launch a headless browser. If `uv run playwright install chromium` cannot download Chromium from your network, use an installed Google Chrome: `export PA_BROWSER_CHANNEL=chrome`.

## Database migrations

Migrations are hand-written in `backend/alembic/versions/`. Every tenant-owned table must:

1. carry a `tenant_id` foreign key to `tenant`,
2. call `enable_tenant_rls(table)`,
3. grant the application role only what it needs; append-only tables use `grant_append_only(table)`.

Each migration must downgrade cleanly. `tests/integration/test_migrations.py` runs a full up/down/up round trip.

### Browser end-to-end tests

`make e2e` (or `cd web && npx playwright test`) needs `make up`, and ports 3000 and 8100 free. It:

1. creates (once) and migrates a separate `pricing_e2e` database, wipes it and seeds the scenarios (`backend/tests/support/e2e_seed.py`; Redis DB 14);
2. starts the API on port 8100, a scheduler and a `process` worker against that database, and the web app in dev mode on port 3000;
3. signs in as `pilot-expert` and `pilot-admin` through Keycloak's login page and runs the specs serially, re-seeding where a test changes data.

If Playwright's Chromium cannot be downloaded on your network, use an installed Google Chrome: `E2E_BROWSER_CHANNEL=chrome make e2e`. Set `E2E_BACKEND_LOGS=1` to see the backend processes' logs.
