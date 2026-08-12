## MODIFIED Requirements

### Requirement: Versioned prompt constants

Prompts SHALL be versioned constants V1 through V4. Each version provides: `SHARED_SYSTEM_RULES_V{n}`, `TRANSLATOR_SYSTEM_V{n}`, `TRANSLATOR_REVISION_ADDENDUM_V{n}`, `TRANSLATOR_USER_TEMPLATE_V{n}`, `AUDITOR_SYSTEM_V{n}`, `AUDITOR_USER_TEMPLATE_V{n}`. V4 is the current default and adds Arabic script enforcement and romanization detection. An `ALL_PROMPT_CONSTANTS` dictionary maps all constant names to their values for regression tests. `ALL_PROMPT_CONSTANTS` SHALL be auto-generated at module load via introspection of module-level prompt constants (e.g., a comprehension over `globals()` filtered by a naming convention), NOT hand-maintained as a dict literal. Adding a new prompt constant SHALL NOT require editing `ALL_PROMPT_CONSTANTS` (it is picked up automatically).

#### Scenario: V4 is the current default
- **GIVEN** the nodes use prompt constants
- **WHEN** translate_node and audit_node build their prompts
- **THEN** they use TRANSLATOR_SYSTEM_V4, TRANSLATOR_USER_TEMPLATE_V4, AUDITOR_SYSTEM_V4, AUDITOR_USER_TEMPLATE_V4, and TRANSLATOR_REVISION_ADDENDUM_V4

#### Scenario: ALL_PROMPT_CONSTANTS contains every version
- **GIVEN** the ALL_PROMPT_CONSTANTS dictionary
- **WHEN** its keys are inspected
- **THEN** it contains all V1, V2, V3, and V4 constant names

#### Scenario: ALL_PROMPT_CONSTANTS is auto-generated
- **GIVEN** the `prompts.py` source
- **WHEN** `ALL_PROMPT_CONSTANTS` is inspected
- **THEN** it is built by introspection (e.g., a comprehension over `globals()` filtered by a naming convention or a decorator), not a hand-written dict literal

#### Scenario: a new prompt constant appears in the registry automatically
- **GIVEN** a new module-level prompt constant `TRANSLATOR_SYSTEM_V5` is added to `prompts.py`
- **WHEN** the module is re-imported
- **THEN** `ALL_PROMPT_CONSTANTS["TRANSLATOR_SYSTEM_V5"]` exists without any edit to the registry definition

## ADDED Requirements

### Requirement: Auditor verdict confidence validation

`parse_audit_verdict` (and any other parser that reads an auditor-produced `confidence` field) SHALL validate that the parsed `confidence` is a finite float in the `[0.0, 1.0]` range. An out-of-range value (including `nan` and `inf`) SHALL raise `AuditParseError` (a `LegalTranslationError` subclass) with a message naming the offending value.

#### Scenario: an out-of-range confidence is rejected
- **GIVEN** a raw auditor output with `confidence: 1.5`
- **WHEN** parse_audit_verdict is called
- **THEN** `AuditParseError` is raised with a message naming the value 1.5

#### Scenario: a NaN confidence is rejected
- **GIVEN** a raw auditor output with `confidence` parsed as `NaN`
- **WHEN** parse_audit_verdict is called
- **THEN** `AuditParseError` is raised (NaN is not in `[0.0, 1.0]`)

#### Scenario: an infinite confidence is rejected
- **GIVEN** a raw auditor output with `confidence` parsed as `inf`
- **WHEN** parse_audit_verdict is called
- **THEN** `AuditParseError` is raised (inf is not in `[0.0, 1.0]`)

#### Scenario: a valid confidence is accepted
- **GIVEN** a raw auditor output with `confidence: 0.95`
- **WHEN** parse_audit_verdict is called
- **THEN** an AuditVerdict with confidence=0.95 is returned (no exception)
