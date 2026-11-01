#!/usr/bin/env bash
# Run the whole app locally on seeded demo data: API (:8000), scheduler, worker and web (:3000).
#
# Needs `make up` (and the installs) first. Uses the separate `pricing_e2e` database, which is
# wiped and re-seeded on every start. The worker runs the `process` queue only: the demo's
# sources and clearances are fixtures, so it never collects from a website. Ctrl+C stops all.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DB=postgresql+asyncpg://pa_app:pa_app_dev@localhost:55432/pricing_e2e
export PA_ENVIRONMENT=dev
export PA_DATABASE_APP_URL=$DB
export PA_DATABASE_OWNER_URL=postgresql+psycopg://pa_owner:pa_owner_dev@localhost:55432/pricing_e2e
export PA_DATABASE_MAINTENANCE_URL=postgresql+asyncpg://pa_maintenance:pa_maintenance_dev@localhost:55432/pricing_e2e
export PA_REDIS_URL=redis://localhost:56390/14
export PA_S3_BUCKET=pricing-evidence-e2e

for port in 3000 8000; do
  if lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "Port $port is already in use; stop the process using it first." >&2
    exit 1
  fi
done

echo "Seeding demo data (pricing_e2e)..."
uv --directory "$ROOT/backend" run python -m tests.support.e2e_seed reset

pids=()
cleanup() {
  trap - EXIT INT TERM
  echo
  echo "Stopping the demo..."
  kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

uv --directory "$ROOT/backend" run uvicorn --factory pricing_assistant.app:create_app --port 8000 &
pids+=($!)
uv --directory "$ROOT/backend" run python -m pricing_assistant.scheduler &
pids+=($!)
uv --directory "$ROOT/backend" run dramatiq pricing_assistant.workers --queues process --processes 1 &
pids+=($!)
(
  cd "$ROOT/web"
  export BACKEND_API_URL=http://localhost:8000
  export AUTH_SECRET=local-demo-only-auth-secret-0123456789abcdef
  export AUTH_TRUST_HOST=true
  export AUTH_KEYCLOAK_ID=pricing-web
  export AUTH_KEYCLOAK_SECRET=pricing-web-dev-secret
  export AUTH_KEYCLOAK_ISSUER=http://localhost:58080/realms/pricing-assistance
  exec ./node_modules/.bin/next dev --port 3000
) &
pids+=($!)

for _ in $(seq 1 120); do
  if curl -fs -o /dev/null http://localhost:8000/readyz && curl -fs -o /dev/null http://localhost:3000/; then
    cat <<'EOF'

The app is running: http://localhost:3000
Sign in with pilot-admin (admin) or pilot-expert (expert); password: dev-password-1
Press Ctrl+C to stop.
EOF
    wait
    exit 0
  fi
  sleep 1
done
echo "The app did not become ready within 2 minutes; see the logs above." >&2
exit 1
