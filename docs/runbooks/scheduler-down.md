# Scheduler down

The scheduler runs the outbox relay, due fetches, recommendation refresh, the verification-overdue timer, idle review-session closing and the retention purge. Two replicas run; only the holder of the Postgres advisory lock (the leader) runs jobs, and the other takes over within seconds if the leader dies.

**Symptoms:** `SchedulerHeartbeatMissing` / `NoSchedulerLeader` (scraped from the scheduler pods' metrics port), outbox lag growing ([outbox-lag.md](outbox-lag.md)), and no new fetch attempts:

```sql
SELECT max(finished_at) FROM fetch_attempt;   -- should be minutes old at most
```

1. **Pods:**
   ```bash
   oc -n $NS get pods -l app.kubernetes.io/component=scheduler
   oc -n $NS logs deploy/pa-pricing-assistant-scheduler --since=15m
   ```
2. **Crash loop:** read the startup error. The usual causes are database credentials (the Secret), the maintenance role URL, or Redis. Fix it and roll the Deployment (`oc rollout restart deploy/pa-pricing-assistant-scheduler`).
3. **Running but no leader:** the advisory lock is held by a stuck session.
   ```sql
   SELECT pid, state, query_start, application_name FROM pg_stat_activity
   WHERE pid IN (SELECT pid FROM pg_locks WHERE locktype = 'advisory');
   ```
   Restart the scheduler pods first. Terminate the stuck backend (`SELECT pg_terminate_backend(<pid>)`) only if it survives the restart.
4. **After recovery:** the jobs catch up by themselves. Due fetches are scheduled, the outbox drains and overdue verifications are marked. No manual replay is needed.
