# Proposal

## Why

Pricing experts at Iranian computer-hardware retailers check competitor prices by hand across Torob, Digikala and specialist online shops. The checks are scattered and slow, nobody records the evidence behind them, and nothing stops a price from going below the profit floor. The product document "دستیار کارشناس قیمت‌گذاری سخت‌افزار" (v1.0, 2026-10-18; source: `pricing-assistant.html`) describes a decision-support assistant. It turns market observations into a prioritized review queue: each item carries evidence, a deterministic recommendation and a recorded decision by the expert. This change builds that assistant for phase A (proof of data access) and phase B (single-store pilot).

The product is a multi-tenant Tunoo SaaS; the pilot runs one store as one tenant (Q-B1).

## What Changes

- New greenfield application (the repository currently holds only OpenSpec scaffolding):
  - Persian, RTL web workspace for pricing experts.
  - Backend API and background workers.
  - Persistent store for catalog, observations, recommendations and decisions.
- **Catalog ingestion** (R01): file import (CSV/XLSX) of products, inventory, purchase cost and profit rules. It reports errors per row, converts Rial and Toman to one unit, and blocks margin-based recommendations when no valid cost exists.
  - Cost versions record uploader, import and previous value; an implausible cost jump is held for admin confirmation instead of being applied.
- **Market data collection** (R03, data paths A/B):
  - Each source has its own connector: official API, HTML/structured-data extraction, or rendered-page extraction for dynamic pages.
  - **Access clearance gate**: no automated collection from a source, including qualification runs, until its clearance is recorded (approver, date, scope, reference, permitted request rate). Blocking or restrictions are never circumvented.
  - Every observation records source, URL, time, stock, retrieval method and validity.
  - A failed fetch is never treated as out of stock; stale data is labelled against a maximum data age per importance tier.
  - Per-source scheduling, quotas, retries and health metrics.
  - A source-qualification flow (phase A: 20 representative products) decides which cleared sources are reliable.
  - Price and stock extraction is rule-based only.
- **Product matching** (R02): matches competitor offers to our variants on model, capacity, generation, colour/edition, warranty, new/used and cash/instalment. Uncertain matches go to a human confirmation queue. An LLM may extract attributes and propose matches, but never auto-confirms them.
- **Price recommendation** (R04 + financial rule):
  - Deterministic rules produce increase / decrease / hold / insufficient-data / floor-conflict.
  - The profit floor is computed on the net price and converted to the VAT-inclusive comparison basis: `effective cost ÷ (1 − min margin − percentage fees) × (1 + VAT rate)`. The VAT rate is an explicit setting; finance sign-off of the formula is a phase B entry condition.
  - They respect the ceiling, the selected competitors, the per-tier maximum data age and a minimum number of qualifying offers.
  - Outlier offers cannot set the market reference on their own until an expert confirms them.
  - Suggested prices are rounded up to the rounding step (default 10,000 Toman), never below the floor; if rounding removes the undercut, the expert is told.
  - A market price below the floor produces a "floor conflict" result.
  - Each recommendation links to the observation IDs and the rule version used, so it can be reproduced later.
- **Review workspace** (R05):
  - A live, prioritized queue with filters (category, importance, status) and summary cards that open filtered queue views.
  - A detail view with the evidence table (one row per competitor offer, as in Price2Spy).
  - On-demand re-check, limited by source quota and per-expert budget.
- **Pricing decisions and outcome tracking** (R06, R07):
  - Each decision records the expert, time, reason, action and manually applied price.
  - A manually applied price below the floor needs `admin` approval with a reason before the expert may report it as done.
  - Match corrections are traceable.
  - Three outcome states are tracked separately: "expert reported done", "price observed on our site" and "reflected in comparison channel". Channel lag is reported separately and never counts as a site verification failure.
- **No price write-back**: the system has no capability to change prices in the store. This is a hard scope boundary from the source document.
- **LLM assistance** (optional, off until compliance clearance per Q-T2): attribute extraction, match proposals, explanation wording, extraction-rule suggestions (admin-approved) and competitor product URL suggestions (expert-confirmed). The LLM never reads operational prices or stock and never receives cost or margin data.
- **Access control and audit**: admin and expert roles, tenant-scoped data, connector secrets kept server-side only, configurable data retention, and an append-only audit log of state-changing actions.
- **Performance reporting**: measures the pilot targets (≥98% confirmed-match accuracy on a stratified audit sample, 0 recommendations below floor, 100% recommendations with source and time, ≥50% review-time reduction against a per-category baseline), plus tier-A coverage/freshness and price-verification reliability.

Out of scope (from the source document and business answers): automatic price changes, automated competitor-violation reports, instalment financing, coverage of all shops, a "cheapest price" guarantee, out-of-app notifications (SMS, email, Telegram), stock- or sales-driven pricing rules, total-profit forecasts, LLM price reading, multi-language UI, phase C (team roles, advanced prioritization, price-apply integration).

## Capabilities

### New Capabilities

- `catalog-management`: Importing and validating our products, variants, inventory, effective cost and profit rules, including currency normalization and the VAT basis.
- `market-data-collection`: Source registry with access clearance and qualification, API and page-extraction connectors, scheduled and on-demand observation capture, freshness and failure semantics, source health, data retention.
- `product-matching`: Attribute normalization and matching of competitor offers to our variants under sale conditions, the confirmation queue for uncertain matches, and traceable corrections.
- `price-recommendation`: Deterministic recommendation rules, profit-floor/ceiling calculation, outlier handling, rounding, floor-conflict handling, explanation and reproducibility of every recommendation.
- `review-workspace`: The expert's prioritized live queue, summary cards, evidence detail view and quota-limited re-check, in Persian RTL.
- `pricing-decisions`: Recording expert decisions and manually applied prices, admin-approved below-floor overrides, the three-stage outcome tracking, and the guarantee that the system never writes prices to the store.
- `llm-assistance`: The bounded role of the language model (attribute extraction, match suggestion, explanation wording, extraction-rule and offer-URL suggestions), validation of model outputs, and isolation from untrusted page content.
- `access-control-audit`: Authentication, admin/expert roles, tenant isolation, secret handling and the append-only audit trail.
- `performance-reporting`: Measuring the pilot success metrics and source/operational KPIs.

### Modified Capabilities

None. No specs exist yet.

## Impact

- **New code**: `web/` (Next.js, Persian RTL UI), `backend/` (Python/FastAPI API, domain modules, workers, scheduler), `deploy/` (container images, Helm chart compatible with Kubernetes/OpenShift), `docs/`.
- **New infrastructure dependencies**: PostgreSQL, Redis (job queue + rate limiting), S3-compatible object storage (page evidence), Playwright/Chromium worker image, OIDC identity provider. An LLM provider endpoint is optional and enabled only after compliance review. No paid scraping or proxy service is used without an approved budget.
- **External systems** (read-only, each subject to access clearance):
  - Torob: our own shop's data via the Shop API if the store has access (not yet confirmed); Torob product pages as a candidate competitor source.
  - Digikala product pages as a candidate; dropped from automated collection if clearance is not obtained.
  - Specialist-shop candidates: Lion Computer (`lioncomputer.com`) and Meghdad IT (`meghdadit.com`), comparing only each shop's own offers.
  - Our own storefront pages for outcome verification.
- **Business inputs**: answers are recorded in `business-questions.md` in this change (2026-10-25). Most are proposed decisions. These customer confirmations remain open:
  - Before phase A: per-source clearance (Q-L1), Torob and Digikala access (Q-S2, Q-S3), store platform and sample export (Q-D1), data location and hosting (Q-D3, Q-T1).
  - Before phase B: cost items, rates and VAT accounting, including finance sign-off of the floor formula (Q-D2, Q-P3); actual user count and responsible person (Q-B2); baseline time study (Q-K1); monthly budget (Q-T4).
  - Before enabling the LLM: compliance clearance of a provider (Q-T2).
