# Retention purge

The scheduler leader runs `retention.purge` hourly under the dedicated maintenance database role (the application role cannot delete):

- **Evidence snapshots:** files older than `evidence_retention_days` (default 90) are deleted from object storage, and their records are marked expired.
- **Observations:** deleted only if the tenant set `observation_retention_days`. Recommendations that referenced them are reported as `inputs_purged` and can no longer be replayed. The recommendations themselves are kept.

Every run writes `purge_log` rows and an audit event with counts.

**Check the last runs:**
```sql
SELECT kind, cutoff, deleted_count, run_at FROM purge_log ORDER BY run_at DESC LIMIT 20;
```
```bash
oc -n $NS logs deploy/pa-pricing-assistant-scheduler --since=2h | grep retention
```

**Change the periods** (admin, audited):
```bash
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"evidence_retention_days": 60}' "$API/api/v1/settings"
```

**Failures:**
- Object-storage errors: a file that cannot be deleted stays unexpired and is retried on the next run. Check S3 reachability and credentials.
- Database permission errors: the maintenance role lacks a grant. Migrations set the grants, so compare with `alembic current` and re-run the migration Job.
- A deletion request (for example after a clearance revocation) needs a shorter period for that tenant: set it, wait for the next hourly run, then confirm in `purge_log`.
