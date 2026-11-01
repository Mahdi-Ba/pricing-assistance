# Runbook: phase A source qualification

**Goal:** decide, with evidence, which candidate sources are reliable enough to feed price recommendations. Expected duration: 1–2 weeks once access is ready (business question Q-K3).

**Roles:**

- **Admin (store manager):** runs the qualification and decides.
- **Legal contact:** confirms each source's clearance.
- **Expert:** registers product URLs and reviews matches.

All API paths below are under `/api/v1`; the admin pages under `/sources` do the same through the UI.

## 0. Entry conditions (do not start without them)

| Check | Where |
|---|---|
| Written clearance for every candidate source: approver, date, scope, reference, permitted request rate (Q-L1) | legal file / ticket |
| Store platform export for the catalog sample (Q-D1) | admin |
| Hosting and network location of the collector workers decided (Q-T1) | ops |
| Torob and Digikala access status known (Q-S2, Q-S3) | store owner |

## 1. Register candidate sources

For each candidate (Torob product pages, Digikala product pages, Lion Computer, Meghdad IT), plus our own storefront and our Torob listing:

1. `POST /sources` with name, domain, `connector_key`, method and currency unit. Set a quota at or below the permitted rate.
2. `POST /sources/{id}/clearances` with the written clearance. **Without it nothing is ever fetched.**
3. For our Torob listing: `PUT /sources/{id}/connector-config` with `{"own_seller_name": "<our shop name on Torob>"}`.
4. For the Torob Shop API (only if the store confirms access): store the token with `PUT /sources/{id}/secrets/api_token`. Configure the confirmed endpoint and field names in the connector config.

## 2. Extraction rules (page sources)

1. Save 2–3 real product pages per source with a normal browser session, within the cleared scope. Upload them: `POST /sources/{id}/samples`.
2. Propose a selector rule: `POST /sources/{id}/extraction-rules`. The response shows what it extracted from each sample.
3. Approve it (`POST /extraction-rules/{id}/review`) only if every sample yields the right seller rows, prices and stock.
4. Replace the synthetic fixtures in `fixtures/sources/<connector_key>/` with the saved pages. Make sure the contract tests pass (`make backend-test`).

## 3. Prepare the sample

1. Import the 20-variant sample catalog (`POST /catalog/imports`). Mix tiers and categories (SSD, GPU, RAM).
2. Experts register the product URL of each sample variant on each candidate source (`POST /tracked-offers`).
3. Move each source to `under_evaluation`: `POST /sources/{id}/status` with a reason.

## 4. Run

1. `POST /qualification-runs` with the candidate `source_ids` (the sample is picked from tracked variants, default 20).
2. Workers fetch every tracked offer once, within each source's quota.
3. Watch the run until `status = completed`: `GET /qualification-runs/{id}`.
4. Check source health while the run proceeds: `GET /sources-health?hours=24`. On repeated `blocked` responses, stop and follow `source-blocked.md`.
5. Experts review the proposed matches on the `/matches` page so the match rate reflects confirmed pairs.

Repeat the run on several days, including peak hours. This also measures:

- **Publication delay:** for a few manual price changes, compare the change time with `observed_on_site` and `reflected_in_channel` (Q-W2).
- **Cost per source:** set `estimated_cost_per_request_rial` in the connector config to see costs in the report (Q-T4).

## 5. Review the report

| Metric | Meaning | Suggested bar |
|---|---|---|
| `variants_tracked` | Sample variants with a tracked URL on this source | ≥ 15 of 20 |
| `extraction_success_rate` | Final fetches that produced offers | ≥ 0.9 |
| `match_rate` | Tracked variants whose offer matched (proposed or confirmed) | ≥ 0.8 |
| `freshness_median_seconds` | Age of the newest valid observation at report time | within the tier-A data age (2 h) |
| `limits_encountered` | `blocked` or quota-exhausted results | 0 |
| `cost_rial` | Requests × configured cost per request | within budget |

The bars are suggestions for the pilot; record the reasoning for each decision.

## 6. Decide

For each source: `POST /qualification-runs/{run}/sources/{source}/decision` with `approve` or `reject` and a reason. Approval:

- requires a clearance in force,
- moves the source to `approved`,
- is audited with the clearance reference and the report figures.

Only approved sources feed recommendations.

## 7. Exit

Phase B may start when:

- at least one competitor source and our storefront are approved,
- the finance sign-off of the floor formula is recorded (Q-D2, Q-P3),
- the per-category baseline time study is complete (Q-K1).
