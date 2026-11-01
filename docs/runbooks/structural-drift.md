# Structural drift (page layout change)

**Symptoms:** fetch errors `unexpected_structure` / `parse_error` for one source, or observations suddenly marked `suspect_unit`. Extraction never guesses: when the active rule no longer finds prices, the attempt fails rather than recording a wrong price.

1. **Confirm.** Open a failing tracked offer's URL in a browser, and compare it with the stored sample pages of the source (`/sources` → source → extraction rules).
2. **Add current samples.** Upload 1–3 current pages of the source:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOKEN" -F url=https://<domain>/p/123 -F file=@page.html "$API/api/v1/sources/<id>/samples"
   ```
3. **Propose a new rule version.** Write it yourself:
   ```bash
   curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d @rule.json "$API/api/v1/sources/<id>/extraction-rules"
   ```
   Or, only if an LLM provider is cleared, ask for a suggestion: `POST /api/v1/sources/<id>/extraction-rules/suggest`. Both are stored as `proposed`, with their results on every sample.
4. **Review and approve** in `/sources` (or `POST /api/v1/extraction-rules/<rule-id>/review` with `{"decision":"approve","reason":"…"}`). Approval is possible only when the rule extracted offers from every sample. The previous active rule is retired.
5. **Watch** the next fetches (`/sources` health). If the source cannot be fixed quickly, suspend it ([source-failure.md](source-failure.md), step 3).
