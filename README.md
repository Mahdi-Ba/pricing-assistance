# Pricing Assistance

Decision-support assistant for hardware pricing experts (دستیار کارشناس قیمت‌گذاری سخت‌افزار). It collects competitor prices from cleared sources, matches offers to the store's variants, computes deterministic, floor-safe price recommendations and records the expert's decisions. It never changes prices in the store.

The specification lives in `openspec/changes/add-pricing-assistant-mvp/` (proposal, specs, design, tasks, business questions).

## Repository layout

| Path | Content |
|---|---|
| `backend/` | Python 3.12 / FastAPI API, domain modules, Dramatiq workers, scheduler, Alembic migrations |
| `web/` | Next.js (App Router) Persian RTL workspace |
| `deploy/helm/` | Helm chart for Kubernetes / OpenShift |
| `deploy/compose/` | Local stack: PostgreSQL, Redis, MinIO, Keycloak |
| `docs/` | Architecture, local development, runbooks, ADRs |
| `fixtures/sources/` | Recorded source responses for connector contract tests |

## Quick start

Prerequisites: Docker with Compose v2, [uv](https://docs.astral.sh/uv/), Node.js 22+ and GNU make.

```bash
make help        # list targets
make up          # start the local stack (Postgres, Redis, MinIO, Keycloak)
make backend-install web-install
make browsers    # headless Chromium for the rendered-page tests (~100 MB, once per machine)
make migrate
make test
```

## Run the app

`make test` only checks the code; it does not start the app. To use it in the browser:

```bash
make demo        # needs `make up`; seeds demo data and starts the API, workers and web app
```

Then open http://localhost:3000 and sign in with `pilot-admin` (admin) or `pilot-expert` (expert), password `dev-password-1`. Ctrl+C stops everything. The demo never fetches from real websites.

See `docs/local-dev.md` for details and `docs/architecture.md` for the architecture overview.

Deployment (images, Helm chart, split collector topology): [docs/deployment.md](docs/deployment.md). Operations runbooks: [docs/runbooks/](docs/runbooks/README.md).
