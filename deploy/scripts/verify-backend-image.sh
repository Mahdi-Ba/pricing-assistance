#!/bin/bash
# Runs the backend image as an arbitrary UID with a read-only root filesystem against the local
# stack (`make up`, demo data in pricing_e2e): API, migrations, scheduler and worker (task 14.1).
# Usage: deploy/scripts/verify-backend-image.sh [image]
H=host.docker.internal
ENV=(-e PA_ENVIRONMENT=dev
  -e PA_DATABASE_APP_URL=postgresql+asyncpg://pa_app:pa_app_dev@$H:55432/pricing_e2e
  -e PA_DATABASE_OWNER_URL=postgresql+psycopg://pa_owner:pa_owner_dev@$H:55432/pricing_e2e
  -e PA_DATABASE_MAINTENANCE_URL=postgresql+asyncpg://pa_maintenance:pa_maintenance_dev@$H:55432/pricing_e2e
  -e PA_REDIS_URL=redis://$H:56390/14 -e PA_S3_ENDPOINT_URL=http://$H:59000
  -e PA_S3_BUCKET=pricing-evidence-e2e -e PA_OIDC_ISSUER=http://$H:58080/realms/pricing-assistance)
RO=(--user 1000680000:0 --read-only --tmpfs /tmp)
IMG=${1:-pricing-backend:local}
echo "== uid, root fs read-only, /tmp writable"
docker run --rm "${RO[@]}" "$IMG" sh -c 'id -u; touch /app/x 2>&1 | tail -1; touch /tmp/ok && echo tmp-writable'
echo "== migrations (alembic current)"
docker run --rm "${RO[@]}" "${ENV[@]}" "$IMG" alembic current 2>&1 | tail -1
echo "== api"
docker run -d --name pa-ro-api "${RO[@]}" "${ENV[@]}" -p 18000:8000 "$IMG" >/dev/null
sleep 6; curl -s localhost:18000/readyz; echo; echo "metric families: $(curl -s localhost:18000/metrics | grep -c '^# HELP')"
docker logs pa-ro-api 2>&1 | grep -iE "read-only|permission denied|Traceback" | head -3
docker rm -f pa-ro-api >/dev/null
echo "== scheduler + worker, metrics on 9100"
docker run -d --name pa-ro-sched "${RO[@]}" "${ENV[@]}" -e PA_METRICS_PORT=9100 -p 19100:9100 "$IMG" python -m pricing_assistant.scheduler >/dev/null
docker run -d --name pa-ro-worker "${RO[@]}" "${ENV[@]}" -e PA_METRICS_PORT=9100 -p 19101:9100 "$IMG" dramatiq pricing_assistant.workers --queues process --processes 1 --threads 1 >/dev/null
sleep 12
curl -s localhost:19100/metrics | grep "^pa_scheduler_heartbeat"
echo "worker pa_ metric families: $(curl -s localhost:19101/metrics | grep -c '^# HELP pa_')"
docker logs pa-ro-sched 2>&1 | grep -iE "read-only|permission denied|Traceback" | head -3
docker logs pa-ro-worker 2>&1 | grep -iE "read-only|permission denied|Traceback" | head -3
docker rm -f pa-ro-sched pa-ro-worker >/dev/null
