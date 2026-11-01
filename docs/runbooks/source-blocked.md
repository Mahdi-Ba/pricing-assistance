# Source blocked

**Symptoms:** `SourceBlocked`; fetch errors of class `blocked` (HTTP 403, 429 or a challenge page).

**What the system already did:** it did not retry. It paused the source for `Retry-After` (default 15 minutes). Every other request to the source waits for the pause to end.

**Never circumvent the block.** No proxy rotation, no User-Agent or identity changes, no CAPTCHA solving, no headless tricks. These are forbidden by design and by the clearance.

1. Confirm the pattern with `blocked` counts per source (`/sources` or `GET /api/v1/sources-health?hours=24`).
2. **Single, short block** (for example a 429 with `Retry-After`): no action. The pause ends by itself.
3. **Repeated blocks** (more than once in a day): suspend the source now.
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"status":"suspended","reason":"blocked repeatedly; contacting source owner"}' "$API/api/v1/sources/<id>/status"
   ```
4. **Contact the source owner** through the clearance's contact (see `GET /api/v1/sources/<id>/clearances`, field `reference`). Agree on a rate, an API or an allow-list.
5. **Resume only with written agreement.**
   - Record a new clearance with the agreed permitted rate (`POST /api/v1/sources/<id>/clearances`).
   - Set the quota at or below it.
   - Move the source back to `approved` (or `under_evaluation` to re-qualify).
6. If no agreement is possible, reject the source (`status: rejected`) and remove its tracked offers from the experts' expectations.
