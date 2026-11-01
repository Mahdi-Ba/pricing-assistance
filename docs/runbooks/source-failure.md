# Source failure

**Symptoms:** `SourceSuccessRateLow` (success < 80% over 1 h); in the queue, «دریافت ناموفق از منبع» / «قدیمی» badges and `insufficient_data` (`stale_evidence`) for variants that depend on the source.

**Impact:** recommendations that relied on the source fall back to `insufficient_data` once its data is older than the tier's maximum age. They never use stale prices. No wrong price is suggested, but coverage drops.

1. **See what fails.** Group the source's error classes and request counts:
   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" "$API/api/v1/sources-health?hours=1" | jq '.[] | {name, success_rate, errors, blocked, data_age_max_seconds}'
   ```
   Or open `/sources` in the web app.
2. **Classify.**
   | `errors` key | Meaning | Action |
   |---|---|---|
   | `network`, `timeout`, `http_error` | site down or slow; retried automatically (3 attempts with backoff) | wait; if it lasts > 1 h, step 3 |
   | `blocked` | 403/429/challenge | **[source-blocked.md](source-blocked.md)** |
   | `unexpected_structure`, `parse_error` | page layout changed | **[structural-drift.md](structural-drift.md)** |
   | `clearance_missing` | clearance revoked or source not collectable | [clearance-revocation.md](clearance-revocation.md) |
   | `quota_exhausted` | our own limiter; too many offers for the quota | lower the tier frequencies or raise the quota within the clearance (`PATCH /api/v1/sources/{id}/settings`) |
   | `off_domain`, `client_error` | a tracked URL moved or redirects off-domain | fix or pause the tracked offer (`POST /api/v1/tracked-offers/{id}/pause`) |
3. **Long outage.** Suspend the source so it stops feeding recommendations and stops being fetched:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"status":"suspended","reason":"site down since 10:00, ticket OPS-123"}' "$API/api/v1/sources/<id>/status"
   ```
   Tell the experts. Their queue shows the source's offers as failed or stale.
4. **Recovery.** Move the source back (`approved`). The scheduler picks its offers up at the next due time, and the recommendations recover by themselves.
