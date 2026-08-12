## ADDED Requirements

### Requirement: ollama_num_ctx config field

`AppConfig` SHALL expose an `ollama_num_ctx: int` field (default 2048) that controls the Ollama KV-cache context size (`num_ctx` in the Ollama `options` dict). The field MUST be validated as a positive integer (> 0) by the existing `_positive_int` field validator. This field is independent of `context_window` (the pipeline-level prompt-truncation budget): `ollama_num_ctx` is the Ollama server-side KV-cache budget, while `context_window` limits how much context the pipeline assembles before sending it to the LLM.

#### Scenario: Default value is 2048
- **GIVEN** an `AppConfig` constructed with no explicit `ollama_num_ctx`
- **WHEN** the field is read
- **THEN** it equals 2048

#### Scenario: Custom value accepted
- **GIVEN** an `AppConfig` constructed with `ollama_num_ctx=4096`
- **WHEN** the field is read
- **THEN** it equals 4096

#### Scenario: Zero is rejected
- **GIVEN** an `AppConfig` constructed with `ollama_num_ctx=0`
- **WHEN** Pydantic validation runs
- **THEN** a `ValidationError` is raised

#### Scenario: Negative value is rejected
- **GIVEN** an `AppConfig` constructed with `ollama_num_ctx=-1024`
- **WHEN** Pydantic validation runs
- **THEN** a `ValidationError` is raised

#### Scenario: config.yaml value overrides the default
- **GIVEN** a `config.yaml` containing `ollama_num_ctx: 4096`
- **WHEN** `load_config` parses it
- **THEN** the resulting `AppConfig.ollama_num_ctx` equals 4096
