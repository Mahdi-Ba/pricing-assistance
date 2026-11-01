# Outbox lag (events not processed)

**How events flow:** a state change writes an event to `outbox_event` in the same transaction. The scheduler leader's relay (every second) sends it to Redis/Dramatiq, and the workers consume it. Lag means the queue does not refresh, recommendations are not recomputed, and outcomes are not verified.

**Symptoms:** `OutboxLagHigh` (oldest undispatched event older than 5 minutes), or the SQL check below.

```sql
SELECT count(*), min(occurred_at), now() - min(occurred_at) AS lag
FROM outbox_event WHERE dispatched_at IS NULL;
```
(Run it per tenant, or as the owner role to see all tenants.)

1. **Is a scheduler leader running?** If not, go to [scheduler-down.md](scheduler-down.md).
   ```bash
   oc -n $NS get pods -l app.kubernetes.io/component=scheduler
   oc -n $NS logs deploy/pa-pricing-assistant-scheduler --since=10m | grep -E 'scheduler.job_failed|leader'
   ```
2. **Relay errors** (`scheduler.job_failed` with `job=outbox.relay`): usually Redis is unreachable. Check Redis health and the NetworkPolicy egress to Redis. Events stay in the outbox and are sent once Redis is back; nothing is lost.
3. **Events dispatched but not consumed:** the workers are down or behind.
   ```bash
   oc -n $NS get deploy | grep worker
   redis-cli -u "$PA_REDIS_URL" LLEN dramatiq:process   # queue depth per queue
   ```
   Scale the workers up (`oc scale deploy/pa-pricing-assistant-worker-process --replicas=4`) or let the autoscaler act. Check the worker logs for a failing consumer.
4. **One poisoned event** (the same consumer error repeated): consumers are idempotent and retry with backoff. After `max_retries` the message goes to Dramatiq's dead-letter queue (`dramatiq:process.XQ`). Fix the cause, then re-enqueue it from there.
