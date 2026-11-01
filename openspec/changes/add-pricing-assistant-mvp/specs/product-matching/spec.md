# Spec Delta

## Purpose

Decides whether a competitor offer is the same product under the same sale conditions as one of our variants. Uncertain cases go to a human, and every match decision is traceable.

## ADDED Requirements

### Requirement: Normalized matching attributes
The system SHALL normalize each tracked offer into structured attributes: brand, model, manufacturer part number and GTIN when available, capacity, generation, colour/edition, warranty provider and duration, condition (new/used/open-box) and payment type (cash/instalment). Each attribute SHALL keep a source: `structured_data`, `rule`, `llm` or `human`.

#### Scenario: Title normalized
- **WHEN** an offer title reads «حافظه SSD سامسونگ 990 PRO ظرفیت 1 ترابایت گارانتی ۳۶ ماهه»
- **THEN** the offer has brand `Samsung`, model `990 PRO`, capacity `1TB`, warranty duration `36 months`, each with its attribute source recorded

### Requirement: Match states
Each offer-to-variant match SHALL have one state: `proposed`, `confirmed`, `rejected` or `needs_review`. Only `confirmed` matches SHALL feed recommendations.

#### Scenario: Proposed match not used
- **WHEN** a match is in state `proposed`
- **THEN** the offer's price does not contribute to the market reference for that variant

### Requirement: Condition mismatch separation
A match where product identity agrees but a sale condition differs (warranty, new/used/open-box, payment type or delivery terms) SHALL be flagged `condition_mismatch`. It SHALL be shown as evidence but SHALL NOT be treated as an equivalent offer until an expert confirms equivalence with a documented reason. The pricing basis is new, cash, official or equivalent warranty.

#### Scenario: Different warranty
- **WHEN** the competitor's RTX 4060 offer has a different warranty provider from ours
- **THEN** the match is `needs_review` with flag `condition_mismatch: warranty`, and the variant's recommendation is `insufficient_data` with reason "warranty differs; confirm equivalence"

### Requirement: Uncertain matches require human confirmation
Matches whose confidence is below the auto-confirm threshold SHALL enter the confirmation queue. Matches proposed by an LLM SHALL never be auto-confirmed. A match MAY be auto-confirmed only when a valid identifier (manufacturer part number, or GTIN with a correct check digit) is equal and model, part number, capacity, colour/edition, warranty and condition are all identical.

#### Scenario: LLM-proposed match
- **WHEN** the LLM proposes that an offer matches variant V with confidence 0.97
- **THEN** the match is `proposed` and appears in the confirmation queue

#### Scenario: Exact identifier match
- **WHEN** an offer's structured data contains the same manufacturer part number as variant V and all listed attributes and conditions are equal
- **THEN** the match is auto-confirmed with source `rule` and this is recorded in the audit log

#### Scenario: Invalid GTIN
- **WHEN** an offer's GTIN equals variant V's GTIN but fails the check-digit validation
- **THEN** the match is not auto-confirmed and goes to the confirmation queue

### Requirement: Expert match decisions
An expert SHALL be able to confirm, reject or re-assign a match. A reason is required for reject, re-assign and for confirming equivalence despite a `condition_mismatch`. Each decision records actor, time and previous state.

#### Scenario: Expert rejects match
- **WHEN** an expert rejects a match with reason «نسل متفاوت»
- **THEN** the match state becomes `rejected`, the offer stops contributing to recommendations, and the history shows actor, time, reason and previous state

#### Scenario: Equivalence confirmed
- **WHEN** an expert confirms a `condition_mismatch: warranty` match as equivalent without a reason
- **THEN** the confirmation is refused until a reason is entered

### Requirement: Traceable match corrections
Correcting a previously confirmed match SHALL create a new match record version, never an overwrite. Recommendations already issued SHALL keep referencing the match version they used.

#### Scenario: Confirmed match corrected
- **WHEN** an expert re-assigns a confirmed offer from variant V1 to V2
- **THEN** a new version links the offer to V2, the V1 version is retained as superseded, and earlier recommendations for V1 still show the original match

### Requirement: Rejected pairs are not re-proposed
A rejected offer–variant pair SHALL NOT be proposed again automatically unless the offer's normalized attributes change.

#### Scenario: Re-run after rejection
- **WHEN** matching runs again for an offer whose pairing with V was rejected and whose attributes are unchanged
- **THEN** no new proposal for V is created
