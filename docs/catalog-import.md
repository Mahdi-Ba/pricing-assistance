# Catalog import and profit rules

Admins load the store's catalog from a CSV or XLSX file on the **بارگذاری کاتالوگ** page or via `POST /api/v1/catalog/imports`. Download the column template from `GET /api/v1/catalog/import-template`.

## File format

- **CSV** must be UTF-8 (a BOM is allowed). **XLSX** uses the first worksheet.
- The first row holds the column names below; column order does not matter.
- Uploads larger than 5 MB, or workbooks that expand beyond 50 MB, are rejected before parsing.
- Rows are numbered from **1 for the first data row**; the header row is not counted. Empty rows are skipped.

| Column | Required | Meaning |
|---|---|---|
| `sku` | yes | Store SKU; unique; letters, digits and `- _ . /` |
| `product_name` | yes | Product name (variants of one product share it) |
| `category` | yes | Category code in lower-case latin, e.g. `ssd`, `gpu`; profit rules attach to it |
| `brand` | yes | Brand |
| `model` | yes | Exact model of this variant, e.g. `990 PRO 1TB` |
| `current_price` | yes (value may be empty) | Our current selling price, VAT included (the price customers pay) |
| `purchase_cost` | yes (value may be empty) | Purchase cost per unit, **excluding recoverable input VAT**. An empty value marks the variant `cost_missing`; no margin-based recommendation is made for it |
| `currency` | no | `RIAL`/`ریال` or `TOMAN`/`تومان`. If empty, the upload's default currency applies. If neither is set, rows with amounts are rejected |
| `importance` | no | `A`, `B` or `C` (also `الف`, `ب`, `ج`); default `B`. Drives monitoring frequency, data-age limit and queue priority |
| `stock_quantity` | no | Units in stock (shown only; does not change recommendations) |
| `mpn`, `gtin` | no | Manufacturer part number and barcode (GTIN 8/12/13/14 digits); used for exact matching |
| `capacity`, `generation`, `colour_edition` | no | Matching attributes |
| `warranty_provider`, `warranty_months` | no | Our warranty conditions |

Amounts may use Persian or Latin digits and `,` or `٬` thousands separators: `۸٬۴۰۰٬۰۰۰` and `8,400,000` are the same value. Everything is stored as integer Rial; the workspace shows Toman.

## Example

<!-- catalog-import-example:start -->
```csv
sku,product_name,category,brand,model,current_price,purchase_cost,currency,importance,stock_quantity,mpn,capacity,warranty_provider,warranty_months
SSD-990P-1T,Samsung 990 PRO,ssd,Samsung,990 PRO 1TB,"8,900,000","7,500,000",TOMAN,A,4,MZ-V9P1T0BW,1TB,آواژنگ,36
SSD-990P-2T,Samsung 990 PRO,ssd,Samsung,990 PRO 2TB,"۱۶٬۴۰۰٬۰۰۰","۱۳٬۹۰۰٬۰۰۰",تومان,A,2,MZ-V9P2T0BW,2TB,آواژنگ,36
GPU-4060-8G,ASUS Dual RTX 4060,gpu,ASUS,DUAL-RTX4060-O8G,"184,500,000","",RIAL,B,1,90YV0JC0-M0NA00,8GB,ماتریس,24
```
<!-- catalog-import-example:end -->

The GPU row has no purchase cost, so it is imported with status `cost_missing`.

## Import result

Every upload creates an import report (`GET /api/v1/catalog/imports/{id}`). It has a status, counts and a list of errors with row, column and a Persian message.

| Status | Meaning |
|---|---|
| `succeeded` | All rows valid |
| `partially_succeeded` | Valid rows were applied; invalid rows are listed in `errors` |
| `failed` | Every row was invalid |
| `rejected` | A required column is missing; nothing was processed |

Imports are idempotent:

- Variants are matched by SKU and updated only when a value changed.
- A new cost version is written only when the cost differs from the one in force.
- Re-uploading the same file reports every row as `unchanged`.
- `Idempotency-Key` makes a retried upload return the original report.

### Implausible cost changes

A new purchase cost more than **5×** or less than **1/5** of the cost in force is most likely a Rial/Toman mix-up. Such a cost is held (`held`) and the previous cost stays in force. The row appears in the report and in the variant's cost history (`GET /api/v1/catalog/variants/{id}/costs`). An admin then confirms or rejects it with a reason: `POST /api/v1/catalog/costs/{id}/review`.

## Effective cost

`effective cost = purchase cost in force + active fixed per-unit components`

Components are configured under `/api/v1/catalog/cost-components`: for example freight, insurance, customs, warehousing or packaging. A component applies to one category or, with no category, to all.

Percentage costs that depend on the sale amount (marketplace commission, payment fees) are **not** components. They are the rule's `fee_rate_bp`.

## Profit rules

Rules are versioned at three scopes. The most specific value wins, field by field:

| Scope | Endpoint | Notes |
|---|---|---|
| default | `PUT /api/v1/rules/default` | Must set every field except ceiling and competitor set, **including `vat_rate_bp`**, which has no default |
| category | `PUT /api/v1/rules/category/{category}` | Sets only the fields that differ |
| variant | `PUT /api/v1/rules/variant/{variant_id}` | Sets only the fields that differ |

Every change creates a new immutable version; earlier recommendations keep referencing the versions they used. `GET /api/v1/rules/resolved/{variant_id}` shows the merged rule for a variant.

| Field | Unit | Suggested start |
|---|---|---|
| `min_margin_bp` | basis points of the net (VAT-exclusive) price | 1000 (10 %) |
| `fee_rate_bp` | basis points | 0 |
| `vat_rate_bp` | basis points | — set explicitly (0 allowed) |
| `ceiling_rial` | Rial | none |
| `undercut_step_rial` | Rial | 500 000 (50 000 Toman) |
| `hold_tolerance_bp` | basis points | 100 (1 %) |
| `rounding_step_rial` | Rial | 100 000 (10 000 Toman) |
| `max_data_age_{a,b,c}_seconds` | seconds | 7200 / 14400 / 86400 |
| `outlier_threshold_bp` | basis points below the median of other offers | 1500 (15 %) |
| `min_qualifying_offers` | count | 1 |
| `competitor_set` | `{source_id: [seller, …]}` | empty = all sellers on approved sources |

`min_margin_bp + fee_rate_bp` must stay below 10 000 for every resolved combination. `GET /api/v1/rules/suggested-defaults` returns the suggested starting values.

The floor is `effective cost ÷ (1 − margin − fee) × (1 + VAT)`, rounded up to the rounding step. This formula awaits the store's finance sign-off before phase B (business questions Q-D2, Q-P3).
