# Spec Delta

## Purpose

Gives the pricing expert one Persian RTL workspace: a live, prioritized queue of pricing decisions, the evidence behind each recommendation and the actions needed to resolve it. Alerts are in-app only; out-of-app notifications are out of scope for the MVP.

## ADDED Requirements

### Requirement: Live review queue
The workspace SHALL show a queue of variants with an open recommendation, updated as market data, source health, freshness, floor conflicts, override reviews and expert decisions change. The columns are product and conditions, our price, market reference, suggestion, status and action. All amounts are shown in Toman with Persian digits. Source failures and floor conflicts SHALL carry a visible alert badge.

#### Scenario: Queue loads
- **WHEN** an expert opens the workspace
- **THEN** the queue lists open items, each with product name, conditions summary, our price, market reference (or a stale/failed label), suggestion and status

### Requirement: Queue prioritization
Queue items SHALL be ordered by a priority score. The score combines importance tier, outcome type (`floor_conflict` and `decrease` above others), absolute estimated profit impact and age of the open item. The score inputs SHALL be visible on hover or in detail.

#### Scenario: Tier A floor conflict on top
- **WHEN** the queue contains a tier-A `floor_conflict` and a tier-C `hold`
- **THEN** the tier-A `floor_conflict` is listed first

### Requirement: Queue filters
The queue SHALL be filterable by category, importance tier, outcome, status (needs review, awaiting override approval, decided, awaiting verification, verification overdue) and source health flag. Filters SHALL be reflected in the URL so a view can be shared.

#### Scenario: Filter by status
- **WHEN** the expert selects «نیازمند بررسی»
- **THEN** only items without a recorded decision are shown and the URL includes the filter

### Requirement: Summary cards linked to queue
The workspace SHALL show summary cards: open decisions, more expensive than market, cheaper than market, floor conflicts, stale/failed sources, pending match confirmations and, for admins, overrides awaiting approval. Clicking a card SHALL open the queue filtered to exactly those items. The primary metric SHALL be the number of unresolved decisions.

#### Scenario: Card drill-down
- **WHEN** the expert clicks «گران‌تر از بازار»
- **THEN** the queue shows exactly the items whose outcome is `decrease` or `floor_conflict` because our price is above the market reference

### Requirement: Evidence detail view
Selecting an item SHALL open a detail view. It shows the recommendation, the Persian explanation, the floor and ceiling, and an evidence table with one row per competitor offer. Each row shows seller, price, stock, conditions, match state, flags (`condition_mismatch`, `price_outlier`, outside competitor set), observed time, freshness label and a link to the source page. Rows that do not qualify for the market reference SHALL say why.

#### Scenario: Evidence row content
- **WHEN** the expert opens Samsung 990 PRO 1TB
- **THEN** each competitor row shows its price, stock, observed time («۸ دقیقه پیش»), match state and a working source link

### Requirement: Match actions from evidence
From the evidence table the expert SHALL be able to reject a match, confirm a `needs_review` match, confirm a `price_outlier` observation with a reason, or request a re-check of a single offer.

#### Scenario: Reject from evidence
- **WHEN** the expert rejects a competitor row as a mismatch with a reason
- **THEN** the match is rejected, the recommendation is recomputed, and the detail view refreshes with the new outcome

#### Scenario: Confirm outlier from evidence
- **WHEN** the expert confirms a row flagged `price_outlier` with a reason
- **THEN** the recommendation is recomputed with that observation qualifying, and the detail view refreshes with the new outcome

### Requirement: Quota-limited re-check
An on-demand re-check SHALL be accepted only if the source quota and the per-user re-check budget allow it. Otherwise the request is refused with the time of the next available slot. Re-check status SHALL be shown until it completes.

#### Scenario: Re-check refused by quota
- **WHEN** the source quota for the current window is exhausted
- **THEN** the re-check is refused with a message showing when it can be retried, and no request is sent

### Requirement: Match confirmation queue view
The workspace SHALL provide a separate view of `proposed` and `needs_review` matches with side-by-side attributes of our variant and the offer, and confirm/reject/re-assign actions. The same view SHALL list `suggested` offer URLs with confirm/dismiss actions.

#### Scenario: Side-by-side compare
- **WHEN** the expert opens a pending match
- **THEN** both items' normalized attributes are shown side by side, with differing attributes highlighted

#### Scenario: Confirm suggested URL
- **WHEN** the expert confirms a suggested offer URL for a variant
- **THEN** it becomes a tracked offer scheduled per the variant's tier, and the confirmation is audited

### Requirement: Persian RTL and Jalali dates
The UI SHALL be right-to-left, in Persian, with Persian digits for amounts and Jalali dates. Product model names SHALL render left-to-right inline. Absolute timestamps SHALL be available alongside relative times.

#### Scenario: Mixed-direction product name
- **WHEN** a row shows «Kingston DDR5 · 32GB / 5600»
- **THEN** the model name renders LTR inside the RTL layout without reordering

### Requirement: Explicit non-application notice
After the expert records a decision, the workspace SHALL state that no price was changed in the store and that the change must be made manually. For a below-floor override, it SHALL also state that the store price must not be changed until an admin approves.

#### Scenario: Notice after decision
- **WHEN** a decision is saved
- **THEN** the confirmation reads that the decision was recorded and no store price was changed

#### Scenario: Notice for pending override
- **WHEN** a decision with a below-floor applied price is saved by an expert
- **THEN** the confirmation states that admin approval is required before the price is changed in the store
