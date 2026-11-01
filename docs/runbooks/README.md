# Runbooks

| Situation | Runbook | Typical trigger |
|---|---|---|
| A source's fetches keep failing | [source-failure.md](source-failure.md) | `SourceSuccessRateLow`, «دریافت ناموفق از منبع» badges |
| A source blocks us (403/429/challenge) | [source-blocked.md](source-blocked.md) | `SourceBlocked` |
| A source's permission is withdrawn | [clearance-revocation.md](clearance-revocation.md) | legal/business notice |
| A source changed its page layout | [structural-drift.md](structural-drift.md) | `unexpected_structure` errors |
| Events are not being processed | [outbox-lag.md](outbox-lag.md) | `OutboxLagHigh` |
| No scheduler is running | [scheduler-down.md](scheduler-down.md) | `SchedulerHeartbeatMissing`, `NoSchedulerLeader` |
| Rotate the connector-secret encryption key | [key-rotation.md](key-rotation.md) | schedule / suspected leak |
| Retention purge failed or must be checked | [retention-purge.md](retention-purge.md) | purge job errors |
| Roll back / stop the system | [rollback.md](rollback.md) | serious defect |
| Phase A source qualification | [qualification.md](qualification.md) | phase A |
| Phase entry and decision gates | [phase-gates.md](phase-gates.md) | before each phase |

Conventions used in every runbook:

- **Never circumvent a block.** No proxy rotation, identity spoofing, CAPTCHA solving or "looking human". If a source does not want to be read, suspend it and talk to its owner.
- **API calls:** `$API` is the API base URL, and `$TOKEN` is an admin access token. Every write is audited under your user. Requests that change state accept an `Idempotency-Key` header.
- **Commands:** `oc` works the same as `kubectl`. `$NS` is the namespace, and `pa-` is the Helm release prefix.
- **SQL:** read-only queries run with `psql` as the application role and need the tenant set first: `SELECT set_config('app.tenant_id', '<tenant uuid>', false);`.

> **Metrics:** the API serves `/metrics` on its HTTP port; the scheduler and worker processes serve it on `PA_METRICS_PORT` (the chart sets 9100). The alerts in `deploy/prometheus/alerts.yaml` rely on both. The SQL and log checks in each runbook remain useful when Prometheus itself is unavailable.

These runbooks have not yet been rehearsed on staging (task 14.5). Update any command that differs there.
