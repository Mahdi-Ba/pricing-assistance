# Spec Delta

## Purpose

Produces deterministic, explainable and reproducible price recommendations for each variant from confirmed fresh market evidence and the store's profit rules. The profit floor is never violated.

## ADDED Requirements

### Requirement: Recommendation outcomes
For each variant, the engine SHALL produce exactly one outcome: `increase`, `decrease`, `hold`, `insufficient_data` or `floor_conflict`. `increase` and `decrease` SHALL include a suggested price. Every outcome SHALL include a reason code.

#### Scenario: Cheaper comparable competitor
- **WHEN** our price is 89,000,000 Rial, the market reference is 86,000,000 Rial, the floor is 84,000,000 Rial and the undercut step is 500,000 Rial
- **THEN** the outcome is `decrease` with suggested price 85,500,000 Rial and reason `above_market`

#### Scenario: We are cheaper than the market
- **WHEN** our price is 82,000,000 Rial, the market reference is 86,000,000 Rial, the floor is 80,000,000 Rial, the undercut step is 500,000 Rial and the hold tolerance is 1%
- **THEN** the outcome is `increase` with suggested price 85,500,000 Rial and reason `below_market`

### Requirement: Deterministic calculation
Recommendation calculation SHALL be deterministic. The same inputs (observations, matches, catalog values, rule version) SHALL always produce the same output. Language models SHALL NOT compute prices, floors or margins.

#### Scenario: Replay
- **WHEN** a stored recommendation is recomputed from its referenced inputs
- **THEN** the recomputed outcome and price are identical to the stored ones

### Requirement: Profit floor formula
The floor SHALL be computed on the net (VAT-exclusive) selling price and converted to the VAT-inclusive basis on which our price and competitor prices are compared: `floor_net = effective_cost ÷ (1 − min_margin − percentage_fee_rate)` and `floor = floor_net × (1 + vat_rate)`, rounded up to the configured rounding step. Minimum margin and percentage fees are rates on the net selling price. This SHALL NOT be computed as cost plus a markup. Without a configured VAT rate, the engine SHALL NOT produce a margin-based recommendation.

#### Scenario: 10% margin, no fees, VAT 0%
- **WHEN** effective cost is 90,000,000 Rial, minimum margin is 10%, percentage fees are 0% and the VAT rate is 0%
- **THEN** the floor is 100,000,000 Rial (not 99,000,000)

#### Scenario: Margin with percentage fee
- **WHEN** effective cost is 90,000,000 Rial, minimum margin is 10%, percentage fee is 5% and the VAT rate is 0%
- **THEN** the floor is 105,882,352.94 Rial before rounding (105,882,353 at a 1-Rial step), rounded up to the configured step

#### Scenario: VAT-inclusive comparison
- **WHEN** effective cost is 90,000,000 Rial, minimum margin is 10%, percentage fees are 0% and the VAT rate is 10%
- **THEN** the net floor is 100,000,000 Rial and the floor used for comparison is 110,000,000 Rial

#### Scenario: VAT basis not configured
- **WHEN** no VAT rate is configured for the tenant
- **THEN** the outcome is `insufficient_data` with reason `tax_basis_unset`

### Requirement: Floor is never violated
The engine SHALL NOT suggest any price below the floor. If the market reference is below the floor, the outcome SHALL be `floor_conflict`, without a suggested price, for expert review.

#### Scenario: Market below floor
- **WHEN** the floor is 84,000,000 Rial and the market reference is 82,000,000 Rial
- **THEN** the outcome is `floor_conflict`, no price is suggested, and the explanation shows both values

### Requirement: Ceiling is respected
When a ceiling is configured, an `increase` suggestion SHALL NOT exceed it.

#### Scenario: Increase capped
- **WHEN** the market reference allows 120,000,000 Rial and the ceiling is 115,000,000 Rial
- **THEN** the suggested price is 115,000,000 Rial with reason `capped_by_ceiling`

### Requirement: Market reference
The market reference SHALL be the lowest price among qualifying offers. An offer qualifies when it is confirmed and condition-equivalent, in stock, fresh for the variant's tier, from an approved source, within the rule's selected competitor set (all sellers on approved sources when no set is configured), and not an unconfirmed `price_outlier`. The engine SHALL report how many offers qualified and their median price. When fewer offers qualify than the rule's minimum qualifying offers (default 1), the outcome SHALL be `insufficient_data`.

#### Scenario: Out-of-stock offer ignored
- **WHEN** the cheapest confirmed offer is `out_of_stock`
- **THEN** it is excluded and the next cheapest qualifying offer becomes the market reference

#### Scenario: Seller outside competitor set
- **WHEN** the rule's competitor set for a source lists sellers S1 and S2 and the cheapest confirmed offer is from seller S3
- **THEN** the S3 offer is shown as evidence but is not used as the market reference

### Requirement: Outlier offers
An offer SHALL be flagged `price_outlier` when at least 2 other qualifying offers exist for the variant and its price is lower than the median of those other offers by more than the rule's outlier threshold (default 15%). A flagged offer SHALL be shown as evidence and SHALL NOT set the market reference until an expert confirms that observation with a reason. The confirmation SHALL apply only to that observation; a new observation of the offer is evaluated again.

#### Scenario: Outlier excluded
- **WHEN** qualifying offers are 86,000,000, 87,000,000 and 70,000,000 Rial and the outlier threshold is 15%
- **THEN** the 70,000,000 Rial offer is flagged `price_outlier` (19% below the median 86,500,000 of the others), and the market reference is 86,000,000 Rial

#### Scenario: Outlier confirmed by expert
- **WHEN** an expert confirms the flagged 70,000,000 Rial observation with a reason
- **THEN** the recommendation is recomputed with 70,000,000 Rial as the market reference, and the confirmation is audited

### Requirement: Hold within tolerance
When our price is within the rule's hold tolerance of the market reference, the outcome SHALL be `hold`.

#### Scenario: Small gap
- **WHEN** the hold tolerance is 1% and our price is 0.5% above the market reference
- **THEN** the outcome is `hold` with reason `within_tolerance`

### Requirement: Price rounding
Suggested prices SHALL be rounded up to the rule's rounding step (default 100,000 Rial, which is 10,000 Toman). Rounding SHALL never produce a price below the floor. If rounding up would exceed the ceiling, the ceiling SHALL be used. After rounding, if the suggested price equals our current price, the outcome SHALL be `hold` with reason `no_change_after_rounding`. If a rounded `decrease` suggestion is no longer below the market reference, the recommendation SHALL carry the flag `undercut_lost` and the explanation SHALL say so.

#### Scenario: Rounded up
- **WHEN** the market reference is 85,990,000 Rial, the undercut step is 500,000 Rial and the rounding step is 100,000 Rial
- **THEN** the suggested price is 85,500,000 Rial (85,490,000 rounded up)

#### Scenario: Undercut lost by rounding
- **WHEN** our price is 89,000,000 Rial, the market reference is 85,980,000 Rial, the undercut step is 50,000 Rial, the floor is 84,000,000 Rial and the rounding step is 100,000 Rial
- **THEN** the outcome is `decrease` to 86,000,000 Rial with flag `undercut_lost`, and the explanation states that the rounded price is not below the market reference

### Requirement: Insufficient data
The outcome SHALL be `insufficient_data` when the variant has no valid cost (`missing_cost`), the VAT basis is not configured (`tax_basis_unset`), only matches or outliers pending review exist (`pending_review`), only stale observations exist (`stale_evidence`), fewer offers qualify than the configured minimum (`below_min_offers`) or no offer qualifies (`no_offers`). When several apply, the reason SHALL follow this precedence order.

#### Scenario: Only stale evidence
- **WHEN** all confirmed offers for a variant are stale
- **THEN** the outcome is `insufficient_data` with reason `stale_evidence`

### Requirement: Estimated per-unit profit
`increase` and `decrease` outcomes SHALL include the estimated per-unit profit at the suggested price: `price ÷ (1 + vat_rate) × (1 − percentage_fee_rate) − effective_cost`. The current per-unit profit SHALL be shown alongside it. Total profit based on sales volume is out of scope.

#### Scenario: Profit shown
- **WHEN** a `decrease` to 85,500,000 Rial is suggested with effective cost 75,000,000 Rial, 0% fees and a VAT rate of 0%
- **THEN** the estimated per-unit profit 10,500,000 Rial is included

### Requirement: Recommendation traceability
Each recommendation SHALL be stored immutably. It SHALL reference the observation IDs, match versions, outlier confirmations, catalog snapshot values and profit-rule version used, plus the engine version.

#### Scenario: Audit view
- **WHEN** an auditor opens a recommendation from last week
- **THEN** it shows the exact observations (with source, URL and time), match versions, cost, rule version and engine version used

### Requirement: Recommendation explanation
Each recommendation SHALL carry a Persian explanation. It is generated from the reason code, flags and input values by a deterministic template. LLM wording MAY rephrase it, but SHALL NOT change any number or outcome.

#### Scenario: Explanation content
- **WHEN** a `decrease` is produced
- **THEN** the explanation names the reference competitor, its price and observation time, and the floor value

### Requirement: Recomputation triggers
A variant's recommendation SHALL be recomputed when one of its inputs changes: a new valid observation, a match state change, an outlier confirmation, a cost change or a rule version change. Superseded recommendations SHALL remain stored.

#### Scenario: New observation arrives
- **WHEN** a new valid observation lowers the market reference for variant V
- **THEN** a new recommendation for V is produced and the previous one is marked superseded
