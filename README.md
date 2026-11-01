# Tunoo Pricing Assistant

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

```bash
make help        # list targets
make up          # start the local stack
make backend-install web-install
make migrate
make test
```

See `docs/local-dev.md` for details and `docs/architecture.md` for the architecture overview.

Deployment (images, Helm chart, split collector topology): [docs/deployment.md](docs/deployment.md). Operations runbooks: [docs/runbooks/](docs/runbooks/README.md).
