# Rollback

The assistant never writes to the store or to any channel, so stopping it cannot break the shop. The experts return to the manual process.

**Options, from lightest to strongest:**

1. **One bad source:** suspend it (`POST /api/v1/sources/<id>/status` with `suspended`). Its offers stop feeding recommendations immediately.
2. **Stop all collection:** scale the collector workers to zero. The queue keeps working on existing data, which ages into `insufficient_data` (stale) by tier.
   ```bash
   oc -n $NS scale deploy/pa-pricing-assistant-worker-collect deploy/pa-pricing-assistant-worker-browser --replicas=0
   ```
3. **Roll back a release:**
   ```bash
   helm -n $NS history pa
   helm -n $NS rollback pa <revision>
   ```
   If the bad release included a migration, run its downgrade before the rollback, but only if the downgrade is non-destructive. Every migration has a tested downgrade. Append-only tables are never destructively migrated during the pilot.
   ```bash
   oc -n $NS run pa-downgrade --rm -it --restart=Never --image=<backend image of the target revision> \
     --overrides='{"spec":{"containers":[{"name":"pa-downgrade","image":"<image>","command":["alembic","downgrade","<revision>"],"envFrom":[{"secretRef":{"name":"pricing-migrations"}}]}]}}'
   ```
4. **Stop everything:** scale every Deployment to zero. Data stays in Postgres and object storage.

**After a rollback:**
- Tell the experts which decisions are affected. Decisions and audit events are kept; nothing is deleted.
- When restarting, resume sources one by one.
