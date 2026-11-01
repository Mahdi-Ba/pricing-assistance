# Clearance revocation

**When:** the source owner, legal or Tunoo management withdraws permission to read a source.

1. **Revoke immediately.** This suspends the source and blocks every fetch path (scheduled, re-check, qualification, search). Nothing is sent to the source after this call commits:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"reason":"permission withdrawn by owner, letter 2026-11-02"}' "$API/api/v1/sources/<id>/clearances/revoke"
   ```
   In the web app: `/sources` → source → record the revocation.
2. **Verify** that no fetch attempt for the source happened after the revocation:
   ```sql
   SELECT max(finished_at) FROM fetch_attempt WHERE source_id = '<id>';
   ```
   Fetches already in flight finish. New ones fail with `clearance_missing` without contacting the source.
3. **Effect on recommendations:** the source no longer feeds the market reference. Affected variants are recomputed automatically (`source.status.changed`).
4. **Existing evidence and observations:** they stay subject to the normal retention ([retention-purge.md](retention-purge.md)) unless the revocation requires deletion. In that case, shorten retention for the tenant and run the purge, and record the request in the audit trail.
5. Inform the experts and the pilot owner. Note the revocation in the qualification report if phase A is running.
