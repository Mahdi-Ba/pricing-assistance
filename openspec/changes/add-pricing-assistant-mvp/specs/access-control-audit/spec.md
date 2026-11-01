# Spec Delta

## Purpose

Secures the assistant through authenticated access, least-privilege roles, tenant isolation, server-side secret handling and an append-only audit trail of every state-changing action.

## ADDED Requirements

### Requirement: Authenticated access
All UI and API access SHALL require authentication through the configured OpenID Connect provider. Unauthenticated requests SHALL receive no business data.

#### Scenario: No session
- **WHEN** an unauthenticated request calls the queue API
- **THEN** the response is HTTP 401 and contains no business data

### Requirement: Roles and permissions
The system SHALL support the roles `admin` and `expert`. Admins manage sources, source clearances, connectors, extraction rule approvals, catalog imports, profit rules, retention settings and users; approve or reject below-floor overrides; and audit match samples. Experts review the queue, decide on matches, outliers, suggested offer URLs and recommendations, record decisions and request re-checks within budget. Experts SHALL NOT change sources, clearances, connectors, extraction rules, profit rules or catalog cost, and SHALL NOT approve overrides.

#### Scenario: Expert edits rule
- **WHEN** an expert calls the profit-rule update endpoint
- **THEN** the response is HTTP 403 and an audit event of the denied attempt is written

#### Scenario: Expert approves override
- **WHEN** an expert calls the override approval endpoint
- **THEN** the response is HTTP 403 and an audit event of the denied attempt is written

### Requirement: Tenant isolation
Every business record SHALL belong to exactly one tenant. Every query SHALL be scoped to the caller's tenant at the data-access layer and enforced in the database. A user SHALL NOT read or change another tenant's data.

#### Scenario: Cross-tenant access
- **WHEN** a user of tenant T1 requests a recommendation ID that belongs to tenant T2
- **THEN** the response is HTTP 404 and no data from T2 is returned

### Requirement: Server-side secrets
Connector credentials, API keys and LLM keys SHALL be stored only server-side in a secret store. They SHALL never be sent to the browser, written to logs or included in evidence snapshots.

#### Scenario: Connector config viewed
- **WHEN** an admin views a connector configuration in the UI
- **THEN** secret fields show only whether a value is set, never the value

### Requirement: Append-only audit log
The system SHALL write an append-only audit event for every state-changing action. Covered actions: imports, cost confirmations, rule changes, source status and clearance changes, extraction rule approvals, match decisions, outlier confirmations, offer URL confirmations, recommendation decisions, override requests and reviews, re-check requests, retention changes and purges, role changes and denied authorization attempts. Each event records tenant, actor, action, target, before/after summary, time and correlation ID.

#### Scenario: Audit trail of a decision
- **WHEN** an expert records a decision
- **THEN** an audit event exists with actor, recommendation ID, decision type, reason, time and correlation ID, and the event cannot be updated or deleted through any application interface

### Requirement: Confidential purchase data
Purchase cost and margin data SHALL be stored only in the deployment's own database, SHALL be visible only to users of the owning tenant and SHALL NOT be sent to external services, including LLM providers and source connectors.

#### Scenario: Outbound payload check
- **WHEN** any outbound request to a source or LLM provider is made
- **THEN** it contains no purchase cost, margin or profit-rule values

### Requirement: Input validation
All API inputs SHALL be validated against typed schemas and rejected with a structured error when invalid. Uploaded files SHALL be size-limited and type-checked before parsing.

#### Scenario: Oversized upload
- **WHEN** an admin uploads a catalog file larger than the configured limit
- **THEN** the upload is rejected before parsing with a size error
