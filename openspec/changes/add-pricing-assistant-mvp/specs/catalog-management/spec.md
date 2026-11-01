# Spec Delta

## Purpose

Lets the store load and maintain its own products, variants, inventory, effective cost and profit rules, so pricing recommendations rest on validated internal data.

## ADDED Requirements

### Requirement: Catalog file import
The system SHALL let an admin import products, variants, inventory, purchase cost and current selling price from a CSV or XLSX file using a published column template. An import is processed as one job with a unique import ID and is idempotent: re-uploading an identical file SHALL NOT create duplicate records.

#### Scenario: Valid file is imported
- **WHEN** an admin uploads a template-conformant file with 250 valid rows
- **THEN** the system creates or updates 250 variants and reports the import as succeeded with counts of created, updated and unchanged rows

#### Scenario: Identical file re-uploaded
- **WHEN** the same file content is uploaded a second time
- **THEN** the system reports all rows as unchanged and creates no new records

### Requirement: Row-level import validation
The system SHALL validate every row and report each failure with row number, column and a Persian error message. Invalid rows SHALL be rejected without blocking valid rows. The import result SHALL be retrievable after the upload session ends.

#### Scenario: Mixed valid and invalid rows
- **WHEN** a file contains 10 rows, of which row 4 has a non-numeric cost and row 7 lacks a SKU
- **THEN** 8 rows are imported, and the import report lists row 4 (cost) and row 7 (SKU) with their error messages

#### Scenario: File does not match template
- **WHEN** a file is missing a required column
- **THEN** the whole import is rejected before any row is processed and the missing column is named in the error

### Requirement: Currency normalization
The system SHALL store all monetary amounts as integer Rial. Every imported or observed amount SHALL carry an explicit currency unit (Rial or Toman), declared per row, per upload or in the source configuration, and be converted on entry. The UI SHALL display amounts in Toman with Persian digits, thousands separators and an explicit «تومان» label.

#### Scenario: Toman amount imported
- **WHEN** a row declares currency `TOMAN` and cost `8,400,000`
- **THEN** the stored cost is 84,000,000 Rial and the UI shows «۸٬۴۰۰٬۰۰۰ تومان»

#### Scenario: Unit missing
- **WHEN** a row has a price but no currency and the import has no default currency set
- **THEN** the row is rejected with an error naming the missing currency unit

### Requirement: Effective cost definition
The system SHALL compute a variant's effective cost as purchase cost, excluding recoverable input VAT, plus the fixed per-unit cost components configured by an admin (for example allocated freight, insurance, clearance and customs, warehousing, packaging and attributable fixed overhead). Percentage-based costs that depend on the sale amount (marketplace commission, payment fees and similar) SHALL be stored separately as rates and SHALL NOT be folded into effective cost, so no cost is counted twice.

#### Scenario: Fixed components added
- **WHEN** purchase cost is 80,000,000 Rial and configured fixed components total 2,000,000 Rial per unit
- **THEN** the effective cost is 82,000,000 Rial

### Requirement: Cost versioning and plausibility
Each purchase-cost change SHALL create a new cost record version that stores the import ID, uploader, upload time and previous value. An imported cost more than 5× or less than 0.2× the variant's previous cost SHALL be held as `suspect_unit` and SHALL NOT be applied until an admin confirms it. A confirmed cost change SHALL trigger recomputation before the next recommendation for the variant is shown.

#### Scenario: Toman entered as Rial
- **WHEN** a variant's previous cost is 84,000,000 Rial and a new row declares `TOMAN` with cost `84,000,000`
- **THEN** the new cost (840,000,000 Rial) is held as `suspect_unit`, the previous cost stays in force, and the import report flags the row

#### Scenario: Cost history
- **WHEN** an admin opens a variant's cost history
- **THEN** each version shows value, previous value, import ID, uploader and time

### Requirement: Missing or invalid cost blocks margin-based output
A variant without a valid positive effective cost SHALL be marked `cost_missing`. The recommendation engine SHALL NOT produce a margin-based price for it.

#### Scenario: Cost absent
- **WHEN** a variant has no purchase cost
- **THEN** the variant shows status `cost_missing` and any recommendation for it is `insufficient_data` with reason `missing_cost`

### Requirement: Profit rules
The system SHALL let an admin define versioned profit rules at default, category and variant scope. A rule sets minimum margin on the net selling price, percentage fees, optional ceiling, undercut step, hold tolerance, rounding step, competitor selection (allowed sellers per source), maximum data age per importance tier, outlier threshold and minimum qualifying offers. The default-scope rule SHALL also set the VAT rate of compared prices; it has no default and SHALL be set explicitly (0 is allowed). A rule with minimum margin plus percentage fees of 100% or more SHALL be rejected. The most specific scope wins. Every change SHALL create a new immutable rule version.

Initial values, to be tuned with pilot data: minimum margin 10%, undercut step 50,000 Toman, hold tolerance 1%, rounding step 10,000 Toman, maximum data age A 2 h / B 4 h / C 24 h, outlier threshold 15%, minimum qualifying offers 1, no ceiling.

#### Scenario: Category rule overrides default
- **WHEN** the default minimum margin is 10% and the SSD category rule sets 12%
- **THEN** recommendations for SSD variants use 12%

#### Scenario: Rule edited
- **WHEN** an admin changes the GPU category minimum margin from 8% to 9%
- **THEN** a new rule version is created, the previous version stays readable, and recommendations made earlier still reference the previous version

#### Scenario: VAT rate required
- **WHEN** an admin saves a default-scope rule without a VAT rate
- **THEN** the rule is rejected with an error naming the VAT rate field

### Requirement: Product importance tier
Each variant SHALL carry an importance tier (A, B or C), either imported or defaulted to B. The tier SHALL drive monitoring frequency, maximum data age and queue priority.

#### Scenario: Tier imported
- **WHEN** a row sets importance `A`
- **THEN** the variant is stored with tier A and is scheduled at the tier-A monitoring interval
