# Phase gates

The rollout has three gates (design "Migration Plan"; business question Q-K3). A gate passes only when every item has its closing evidence recorded. Each item names the business question it answers (in [business-questions.md](../../openspec/changes/add-pricing-assistant-mvp/business-questions.md)) and where the evidence lives. Tick an item and write the evidence reference (document, audit event or report link) in the last column.

## Phase A entry: access proof

| # | Item | Business question | Evidence that closes it | Done / reference |
|---|---|---|---|---|
| A1 | Every candidate source has a written clearance: approver, date, scope, reference, permitted rate | Q-L1, Q-S1, Q-S2, Q-S3 | Clearance records per source (`/sources`, `GET /api/v1/sources/{id}/clearances`); procedure in [qualification.md](qualification.md) | |
| A2 | Competitor set agreed: which shops and sellers count | Q-S4 | `competitor_set` in the default or category profit rule (`/rules`, `GET /api/v1/rules`) | |
| A3 | Store platform sample export imports cleanly (20-variant sample) | Q-D1, Q-D4, Q-D5 | Catalog import report with no rejected rows (`/catalog/imports`); format in [catalog-import.md](../catalog-import.md) | |
| A4 | Hosting and network location decided; collector placement only where sources permit access | Q-T1, Q-D3 | Decision record and chosen topology in [deployment.md](../deployment.md) | |
| A5 | Users and roles provisioned in the identity provider (admins, experts) | Q-B2, Q-T3 | Realm/group configuration; login check in [local-dev.md](../local-dev.md) "Development users" for the target realm | |
| A6 | Running-cost budget for sources and infrastructure agreed | Q-T4 | Estimated cost per source in source health (`GET /api/v1/sources-health`) | |
| A7 | LLM stays disabled unless a provider passed compliance review | Q-T2, Q-S6 | `PA_LLM_ENABLED` / `PA_LLM_CLEARED_PROVIDERS` and the review reference in [llm.md](../llm.md) | |

**Phase A exit:** the qualification report is produced, and the source approval decisions are recorded ([qualification.md](qualification.md); audit `source.status.changed`). The site and Torob publication delays and the cost per source have been measured.

## Phase B entry: pilot

| # | Item | Business question | Evidence that closes it | Done / reference |
|---|---|---|---|---|
| B1 | Finance signs off the floor formula, cost items and VAT basis | Q-D2, Q-P3 | Default profit rule version with `vat_rate_bp` whose `reason` cites the sign-off (`GET /api/v1/rules/history?scope=default`) | |
| B2 | Pricing rules configured: market price definition, strategy, rounding, tolerance, undercut, data age per tier, outlier threshold | Q-P1, Q-P2, Q-P4, Q-S5 | Current profit rule versions (`/rules`) | |
| B3 | Treatment of instalment, used and open-box offers, and of our stock level, confirmed | Q-P5, Q-P6 | Match condition rules in the matching spec; recorded decision in [business-questions.md](../../openspec/changes/add-pricing-assistant-mvp/business-questions.md) | |
| B4 | Below-floor approval flow agreed (admin approval, self-approval for admins) | Q-B3 | Override review records in the floor-safety report (`/reports`) | |
| B5 | Per-category baseline review time measured (one-week time study before go-live) | Q-K1 | Baselines entered per category (`/reports`, `GET /api/v1/reports/baselines`) | |
| B6 | Verification window and re-check budgets set | Q-W1, Q-W2, Q-W3 | Tenant settings (`GET /api/v1/settings`: `verification_window_minutes`, `recheck_daily_budget_per_user`) | |
| B7 | Cost update cadence agreed with the store | Q-D6 | Catalog import schedule; import history (`/catalog/imports`) | |
| B8 | Experts onboarded; notifications stay in-app; UI language Persian | Q-B1, Q-B4, Q-B5 | Onboarding record; the workspace (`/queue`) | |

## Phase C decision

Based on the four PRD pilot targets, measured over the pilot period (`/reports`, `GET /api/v1/reports/pilot`). Tier-A coverage and verification reliability are reported too; their targets are set after phase A (tenant setting `kpi_targets`).

| # | Criterion | Business question | Evidence that closes it | Done / reference |
|---|---|---|---|---|
| C1 | Match accuracy ≥ 98% on the monthly stratified audit sample | Q-K2 | Match audit result (`GET /api/v1/reports/match-audits/{id}`) | |
| C2 | Floor safety: 0 suggestions below the floor; overrides listed with approver and reason | Q-K3, Q-B3 | Floor-safety section of the pilot report (`GET /api/v1/reports/pilot`) | |
| C3 | Evidence completeness 100% for actionable recommendations | Q-K3 | Evidence-completeness section of the pilot report (`GET /api/v1/reports/pilot`) | |
| C4 | Review time reduced by ≥ 50% against the category-mix-weighted baseline (not labelled "low sample") | Q-K1, Q-K3 | Review-time section of the pilot report (`GET /api/v1/reports/pilot`) | |
| C5 | Tier-A coverage and verification reliability reported against the targets set after phase A | Q-K3, Q-W2 | Weekly report KPIs (`GET /api/v1/reports/weekly`) | |

No automatic price application is considered at this decision; the system stays read-only towards the store and channels.
