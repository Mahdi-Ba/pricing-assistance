# Spec Delta

## Purpose

Records what the pricing expert decided and did for each recommendation, and verifies separately whether the change appeared on our site and in comparison channels. Below-floor prices need admin approval. The system itself never changes store prices.

## ADDED Requirements

### Requirement: Decision recording
An expert SHALL record a decision against a specific recommendation. The decision type is `accept`, `accept_modified`, `reject` or `defer`. The record includes a mandatory free-text reason. The system records actor and timestamp.

#### Scenario: Decision without reason
- **WHEN** an expert submits a decision with an empty reason
- **THEN** the decision is refused with the message «برای ثبت، یادداشت تصمیم را وارد کنید.»

#### Scenario: Accept recorded
- **WHEN** an expert accepts a `decrease` recommendation with a reason
- **THEN** the decision is stored with actor, time, recommendation ID and reason, and the queue item status becomes «تصمیم ثبت شد»

### Requirement: Manually applied price
For `accept` and `accept_modified`, the expert SHALL enter the price they set manually in the store. The system SHALL never suggest a price below the floor; a below-floor price can only come from a manually entered applied price.

#### Scenario: Applied price at or above floor
- **WHEN** an expert records `accept_modified` with an applied price at or above the floor
- **THEN** the decision is stored without override and the expert may report the change as done

### Requirement: Admin-approved below-floor override
An applied price below the floor in force SHALL be recorded as a below-floor override request with a mandatory override reason, and the decision SHALL be flagged `below_floor_override` with state `override_pending`. A user with the `admin` role SHALL approve or reject the request with a reason. Approvals and rejections SHALL be stored as separate append-only records; the decision itself SHALL NOT be edited. `reported_done` SHALL NOT be accepted while the override is pending or after it was rejected. When the submitting user holds the `admin` role, the override SHALL be recorded as `self_approved` with the reason.

#### Scenario: Modified price below floor
- **WHEN** an expert enters an applied price below the floor with an override reason
- **THEN** the decision is stored flagged `below_floor_override` in state `override_pending`, the queue item shows «در انتظار تأیید مدیر», and an audit event is written

#### Scenario: Report done before approval
- **WHEN** the expert marks a decision with a pending override as done
- **THEN** the request is refused with the message «قیمت زیر کف نیازمند تأیید مدیر است.» and no outcome state is recorded

#### Scenario: Admin approves override
- **WHEN** an admin approves a pending override with a reason
- **THEN** an approval record with approver, time and reason is stored, and the expert can report the change as done

#### Scenario: Admin rejects override
- **WHEN** an admin rejects a pending override with a reason
- **THEN** a rejection record is stored, the item returns to the queue as «نیازمند بررسی», and the expert must record a new decision that supersedes the rejected one

#### Scenario: Admin's own override
- **WHEN** a user with the `admin` role records an applied price below the floor with a reason
- **THEN** the override is recorded as `self_approved` and is reported separately in the floor safety report

### Requirement: Decisions are immutable
Recorded decisions SHALL NOT be edited or deleted. A correction SHALL be a new decision that references and supersedes the earlier one.

#### Scenario: Correction
- **WHEN** an expert corrects the applied price of an earlier decision
- **THEN** a new decision references the original, and both remain visible in history

### Requirement: Decision bound to recommendation version
A decision SHALL reference the exact recommendation version shown to the expert. If the recommendation was superseded before submission, the submission SHALL be refused and the latest version shown.

#### Scenario: Stale submission
- **WHEN** a new observation supersedes the recommendation while the expert is writing a reason
- **THEN** the submission is refused with a notice that the recommendation changed, and the new version is displayed

### Requirement: Three-stage outcome tracking
Each accepted decision SHALL track three independent outcome states. (1) `reported_done`: the expert marks the manual change as done. (2) `observed_on_site`: an own-store observation shows the applied price. (3) `reflected_in_channel`: our listing on a comparison channel (for example Torob) shows the applied price. Each state records time and evidence. The delay from `reported_done` to `observed_on_site` and to `reflected_in_channel` SHALL be recorded separately.

#### Scenario: Reported but not yet observed
- **WHEN** the expert marks a decision as done, and the next own-store observation still shows the old price
- **THEN** the decision shows `reported_done` set and `observed_on_site` pending; it is not treated as verified

#### Scenario: Observed on site
- **WHEN** an own-store observation after `reported_done` shows the applied price
- **THEN** `observed_on_site` is set with the observation ID as evidence

#### Scenario: Channel lag
- **WHEN** `observed_on_site` is set but our Torob listing still shows the old price after the verification window
- **THEN** `reflected_in_channel` stays pending, the decision is not marked `verification_overdue`, and the channel delay is reported separately from the site delay

### Requirement: Verification timeout
If `observed_on_site` is not reached within the configured verification window after `reported_done` (default 2 hours), the decision SHALL return to the queue with status `verification_overdue`. Channel reflection SHALL NOT affect this timeout.

#### Scenario: Overdue
- **WHEN** the verification window is 2 hours and no matching own-store observation arrives in that time
- **THEN** the item reappears in the queue as `verification_overdue`

### Requirement: No price write-back
The system SHALL NOT contain any operation, credential scope or integration that writes prices or stock to the store or to any channel. Store and channel integrations SHALL be read-only.

#### Scenario: Integration scope check
- **WHEN** a store or channel connector is configured
- **THEN** only read scopes are requested and stored, and the API exposes no endpoint that changes an external price

### Requirement: Decision history
The system SHALL show, per variant, the full chronological history of recommendations, decisions, applied prices, override reviews and outcome states.

#### Scenario: History view
- **WHEN** an expert opens a variant's history
- **THEN** each recommendation is listed with its decision, actor, reason, applied price, any override approval or rejection, and outcome states in time order
