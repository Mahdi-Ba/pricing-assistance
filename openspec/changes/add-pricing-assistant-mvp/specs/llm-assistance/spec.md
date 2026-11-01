# Spec Delta

## Purpose

Limits language-model use to bounded assistive tasks: attribute extraction, match suggestion, explanation wording, extraction-rule suggestions and offer-URL suggestions. Every model output needs validation, and suggestions need human approval. Model use stays away from operational price reading, every pricing calculation and every write operation, and is off until a provider passes compliance review.

## ADDED Requirements

### Requirement: LLM disabled until compliance clearance
Language-model use SHALL be disabled by default. It SHALL be enabled only for a provider that has passed the operator's legal, data-location and compliance review. With the model disabled, every capability SHALL work through rule-based processing and human confirmation.

#### Scenario: No provider cleared
- **WHEN** no provider has been cleared
- **THEN** no model call is made, attribute extraction is rule-based, unmatched offers go to the human confirmation queue, explanations use the deterministic text, and no extraction-rule or URL suggestions are produced

### Requirement: Permitted LLM tasks
The system SHALL use a language model only for: (1) extracting normalized attributes from offer titles and descriptions, (2) proposing offer–variant matches with a rationale, (3) rephrasing a deterministic recommendation explanation into plain Persian, (4) suggesting an extraction rule version for a source from its stored sample pages, (5) suggesting competitor offer URLs for a variant from search-result pages already fetched by a connector. The model SHALL NOT read operational price or stock values. No model output SHALL become an active extraction rule, a tracked offer, a confirmed match or a price without human approval. No other component SHALL call the model.

#### Scenario: Price calculation does not use LLM
- **WHEN** a recommendation is computed
- **THEN** no LLM call participates in computing the market reference, floor, ceiling, suggested price or profit

#### Scenario: Extraction rule suggestion
- **WHEN** the model suggests a selector rule for a source whose layout changed
- **THEN** the rule is stored as a `proposed` version with its validation results on the stored sample pages, and it is not used for live extraction until an admin approves it

#### Scenario: Offer URL suggestion
- **WHEN** the model suggests three product URLs on a competitor site for variant V
- **THEN** they are stored as `suggested` targets with the model's rationale, and none is scheduled until an expert confirms it

### Requirement: Schema-validated outputs
Every LLM response SHALL be parsed against a strict output schema. A response that fails validation SHALL be discarded and logged, and the task SHALL fall back to rule-based processing or human review.

#### Scenario: Malformed extraction
- **WHEN** the model returns attributes with an unknown field or invalid capacity format
- **THEN** the response is rejected, the offer's attributes stay rule-derived, and the offer is flagged for human review if required attributes are missing

### Requirement: Explanation wording cannot alter facts
A rephrased explanation SHALL contain every number from the deterministic explanation unchanged and SHALL NOT add new numbers. If this check fails, the deterministic explanation SHALL be shown instead.

#### Scenario: Number altered
- **WHEN** the rephrased text shows a floor of ۸٬۳۰۰٬۰۰۰ while the deterministic floor is ۸٬۴۰۰٬۰۰۰
- **THEN** the rephrased text is discarded and the deterministic explanation is displayed

### Requirement: No tool or write access
LLM calls SHALL be made without tool or function access that can read beyond the supplied input or change system state. Any page the model analyses SHALL have been fetched beforehand by a connector, under the source's clearance and quota.

#### Scenario: Model output requests an action
- **WHEN** model output contains text resembling a command or tool request
- **THEN** it is treated as plain data and no action is executed

### Requirement: Untrusted content isolation
External page content passed to the model SHALL be clearly delimited as untrusted data in the prompt. System instructions SHALL state that it must not be followed as instructions.

#### Scenario: Prompt injection in title
- **WHEN** an offer title contains an instruction to mark all products as matching
- **THEN** the match proposal for that offer is evaluated only on attributes, and the result is still `proposed` pending human confirmation

### Requirement: Data minimization to the model
Requests to the model SHALL NOT include purchase cost, margins, profit rules, supplier data or personal data. Only offer text, the candidate variants' public attributes and public page content from cleared sources may be sent.

#### Scenario: Match proposal payload
- **WHEN** a match proposal request is built
- **THEN** the payload contains only offer text and candidate variant names and attributes, with no cost or margin fields

### Requirement: LLM call observability and budget
Each LLM call SHALL be logged with task type, model identifier, prompt template version, token usage, latency, validation result and correlation ID. Calls SHALL stop when a configured daily budget is reached, with fallback to human review.

#### Scenario: Budget exhausted
- **WHEN** the daily LLM token budget is reached
- **THEN** further extraction tasks use rule-based extraction only, new unmatched offers go to the human confirmation queue, and suggestion tasks are skipped

### Requirement: Provider independence
LLM access SHALL go through a provider-agnostic interface. Provider and model are selected by configuration, so the provider can be changed without changing matching or explanation behaviour.

#### Scenario: Provider switched
- **WHEN** an admin changes the configured provider
- **THEN** extraction, matching proposals, suggestions and explanations keep working under the same schemas and validation
