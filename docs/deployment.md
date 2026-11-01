# Deployment

The system never writes prices to a store, so a deployment can always be rolled back by suspending sources or scaling workers to zero; experts then work manually (see `runbooks/rollback.md`).

For local development no Kubernetes is needed: `make up` plus the processes in `local-dev.md`.

## 1. Images

| Image | Dockerfile | Runs |
|---|---|---|
| `pricing-backend` | `backend/Dockerfile` (UBI 9, Python 3.12) | API, scheduler, `process` and `collect` workers, migrations |
| `pricing-backend-browser` | `backend/Dockerfile.browser` (Playwright/Ubuntu) | `browser` worker only (rendered-page sources) |
| `pricing-web` | `web/Dockerfile` (UBI 9, Node 22, Next.js standalone) | web app / backend-for-frontend |

All three run as a non-root, arbitrary UID that belongs to group 0 (OpenShift restricted SCC), with a read-only root filesystem. Only `/tmp` (and `.next/cache` for web, `/dev/shm` for the browser worker) must be writable; the chart mounts `emptyDir` volumes there.

```bash
docker build -t pricing-backend backend
docker build -f backend/Dockerfile.browser -t pricing-backend-browser backend
docker build -t pricing-web web
# check the security constraints
docker run --rm --user 1000680000:0 --read-only --tmpfs /tmp pricing-backend python -c "import pricing_assistant.app"
docker run --rm --user 1000680000:0 --read-only --tmpfs /tmp --tmpfs /app/.next/cache -p 3000:3000 pricing-web
```

## 2. Helm chart (`deploy/helm/pricing-assistant`)

One Deployment per role: `api`, `scheduler` (2 replicas; one leader by Postgres advisory lock), `worker-process`, `worker-collect`, `worker-browser`, `web`. Plus:

- **Migrations:** `alembic upgrade head` as a `pre-install,pre-upgrade` hook Job, using a separate owner-credential Secret.
- **Autoscaling** (`autoscaling.enabled`): with KEDA, workers scale on queue depth (Redis lists `dramatiq:<queue>`); otherwise a CPU HorizontalPodAutoscaler.
- **Probes:** API `/readyz`, `/healthz`; web `/`.
- **Metrics:** the API serves `/metrics` on port 8000; the scheduler and workers serve it on `metrics.port` (9100, via `PA_METRICS_PORT`). Workers run one Dramatiq process per pod so each pod has one endpoint. Pods carry `prometheus.io/*` annotations; `metrics.podMonitor.enabled` adds a PodMonitor (OpenShift user-workload monitoring). The NetworkPolicies admit scrapes from `metrics.monitoringNamespaceSelector`.
- **NetworkPolicies:** deny by default; per-role egress to Postgres, Redis, S3, OIDC, OTel and the LLM. Collector workers may reach only `networkPolicy.egress.sources.cidrs`.
- **Secrets:** existing Secrets by name, or External Secrets Operator (`secrets.externalSecrets`). Values never contain secrets.
- **Exposure:** OpenShift Route or Ingress for the web app only; the API stays internal.

| Secret | Keys |
|---|---|
| `secrets.backend` | `PA_DATABASE_APP_URL`, `PA_DATABASE_MAINTENANCE_URL`, `PA_REDIS_URL`, `PA_S3_ACCESS_KEY`, `PA_S3_SECRET_KEY`, `PA_SECRET_ENCRYPTION_KEYS` (optional `PA_ANTHROPIC_API_KEY`) |
| `secrets.migrations` | `PA_DATABASE_OWNER_URL` |
| `secrets.web` | `AUTH_SECRET`, `AUTH_KEYCLOAK_SECRET` |

```bash
helm lint deploy/helm/pricing-assistant
helm template pa deploy/helm/pricing-assistant | kubeconform -strict -ignore-missing-schemas -summary
helm upgrade --install pa deploy/helm/pricing-assistant -n pricing -f my-values.yaml
```

Kubernetes NetworkPolicies match IP ranges, not domain names. To allow approved source domains by name on OpenShift, enable `openshift.egressFirewall` in the collector namespace. Otherwise route collectors through an allow-listing egress proxy.

## 3. Split topology: collectors elsewhere (D14, Q-T1)

Collector workers may run in another namespace or cluster that has stable, permitted access to the sources. They are never placed somewhere to get around a source's access restrictions. Install a second release with `values-collectors.example.yaml` (`topology: collectors`). It renders only the `collect` and `browser` workers, with:

- **Credentials:** scoped to the collector role (`secrets.backend: pricing-collector`).
- **Mutual TLS:** client material from `tls.secretName` (`ca.crt`, `tls.crt`, `tls.key`, mounted at `/etc/pa-tls`):
  - **Postgres:** `PGSSLMODE=verify-full`, `PGSSLROOTCERT`, `PGSSLCERT`, `PGSSLKEY` (read by asyncpg).
  - **Object storage:** `PA_S3_CA_BUNDLE`, `PA_S3_CLIENT_CERT`, `PA_S3_CLIENT_KEY`.
  - **Redis:** put TLS in the URL itself:
    `rediss://user:pass@redis.core:6380/0?ssl_cert_reqs=required&ssl_ca_certs=/etc/pa-tls/ca.crt&ssl_certfile=/etc/pa-tls/tls.crt&ssl_keyfile=/etc/pa-tls/tls.key`
- **Egress:** only the core services' addresses and the approved sources (NetworkPolicy plus optional EgressFirewall).

The core release keeps the scheduler, the API and the `process` workers. Both releases use the same Redis and Postgres.

## 4. Status

**Images: verified locally.** All three images build. Run as UID `1000680000` (group 0) with `--read-only --tmpfs /tmp`:

- **Backend:** reports `alembic current` = head, the API is ready and serves `/metrics`, and the scheduler and worker serve metrics on 9100.
  Re-run with `deploy/scripts/verify-backend-image.sh`.
- **Web:** serves the app, the sign-in redirect and the security headers, with `.next/cache` on tmpfs.
- **Browser worker:** headless Chromium renders a Persian page, and the worker starts with metrics.

**Chart: not yet verified.** `helm`/`kubeconform` were not available and there is no OpenShift test cluster. Before the first staging install:

1. Run `helm lint` and `helm template` (both topologies) through `kubeconform`. The CI `chart` job does this.
2. Install on an OpenShift-compatible test cluster with the restricted SCC.
