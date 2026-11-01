# Spec Delta

## Purpose

Measures whether the assistant meets its pilot targets: match accuracy, floor safety, evidence completeness and review-time reduction. It also measures tier-A coverage, price-verification reliability and source and operational KPIs from recorded data rather than estimates.

## ADDED Requirements

### Requirement: Match accuracy sampling
The system SHALL draw a monthly audit sample of confirmed matches (default 200, or all if fewer), stratified by category, source and match confidence band so that every stratum with confirmed matches is represented. An admin re-checks the sample, and the system computes accuracy as correct ÷ reviewed, overall and per stratum. The target is ≥98%. Incorrect matches SHALL be listed for correction.

#### Scenario: Accuracy computed
- **WHEN** a reviewer audits a sample of 200 confirmed matches and marks 3 as incorrect
- **THEN** the report shows 98.5% accuracy for that sample, with sample size and period

#### Scenario: Stratified sample
- **WHEN** a month has 1,000 confirmed matches across 4 categories and 3 sources
- **THEN** the 200-match sample contains matches from every category, source and confidence band that has confirmed matches

### Requirement: Floor safety metric
The system SHALL report the count of recommendations whose suggested price is below the floor in force at creation time. The target is 0. The system SHALL also report `below_floor_override` decisions separately, with requester, approver (or `self_approved`) and reasons.

#### Scenario: Floor safety report
- **WHEN** the pilot report is generated
- **THEN** it shows the number of below-floor suggestions (expected 0) and the number of overrides with requester, approver and reasons

### Requirement: Evidence completeness metric
The system SHALL report the share of actionable recommendations (`increase`, `decrease`) that reference at least one valid observation with source and timestamp. The target is 100%.

#### Scenario: Completeness report
- **WHEN** the pilot report is generated
- **THEN** it shows evidence completeness as a percentage with the count of any non-compliant recommendations

### Requirement: Review time measurement
The system SHALL measure the time from an expert opening an item to recording a decision, and report median and p90 per period and per category. Admins SHALL enter a baseline per category (median minutes per complete review, from a one-week time study of the manual process before go-live). The reduction against the ≥50% target SHALL be computed on the pilot's category mix: per-category baseline and measured medians, weighted by the pilot's decision count per category.

#### Scenario: Reduction against baseline
- **WHEN** the baseline is 6 minutes per item and the measured median is 2.5 minutes
- **THEN** the report shows a 58% reduction against baseline

#### Scenario: Category mix
- **WHEN** baselines are GPU 8 minutes and SSD 4 minutes, and the pilot has 50 GPU decisions with median 3 minutes and 50 SSD decisions with median 2 minutes
- **THEN** the weighted baseline is 6 minutes, the weighted measured time is 2.5 minutes, and the report shows a 58% reduction

### Requirement: Coverage and verification KPIs
The report SHALL include tier-A coverage (share of tier-A variants with at least one qualifying fresh offer), tier-A data age, and price-verification reliability (share of `reported_done` decisions reaching `observed_on_site` within the verification window), plus the site and channel verification delays reported separately. Targets for these KPIs SHALL be configurable and are unset until defined after phase A.

#### Scenario: Verification reliability
- **WHEN** 40 decisions were reported done in a week and 36 reached `observed_on_site` within the window
- **THEN** the report shows 90% verification reliability with the sample size, and no target if none is configured

### Requirement: Operational KPIs
The report SHALL include per-source success rate, data age distribution, cost per source, LLM usage and cost, queue backlog, and time from recommendation to decision.

#### Scenario: Weekly report
- **WHEN** an admin opens the weekly report
- **THEN** all listed KPIs are shown for that week, with the source of each figure

### Requirement: Targets labelled as targets
Reports SHALL label pilot goals as targets and show measured values separately with their sample sizes.

#### Scenario: Small sample
- **WHEN** fewer than 30 decisions exist in the period
- **THEN** the review-time metric is shown with a "low sample" label
