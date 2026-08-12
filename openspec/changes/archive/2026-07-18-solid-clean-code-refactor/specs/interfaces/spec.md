## ADDED Requirements

### Requirement: CLI module single responsibility

The `cli.py` module SHALL contain only Typer app definition and thin command wrappers. Each command function SHALL delegate to dedicated modules: `diagnostics.py` (all `_check_*` doctor functions and `_detect_offload_mode`), `orchestration.py` (`_run_translation`, `_run_translation_streamed`, `_initial_state`, `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`, `_render_provenance`), `tm_commands.py` (`tm_build`, `tm_build_parallel`, `tm_add_parallel` handler logic). Each command function in `cli.py` SHALL be ≤ 20 lines (a thin wrapper that parses args and delegates).

#### Scenario: cli.py contains only command wrappers
- **GIVEN** the `interfaces/cli.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains the Typer `app` and command functions (`doctor`, `translate`, `batch`, `ingest`, `tm_build`, `tm_build_parallel`, `tm_add_parallel`, `ui`); no `_check_*`, `_run_*`, or `_provenance_*` functions

#### Scenario: Diagnostics are in a separate module
- **GIVEN** the `interfaces/diagnostics.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_check_ollama_reachable`, `_check_models_present`, `_check_chroma_dir`, `_check_glossary_db`, `_check_tm_db`, `_check_ram_headroom`, `_detect_offload_mode`

#### Scenario: Orchestration is in a separate module
- **GIVEN** the `interfaces/orchestration.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_run_translation`, `_run_translation_streamed`, `_initial_state`, `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`, `_render_provenance`

#### Scenario: TM commands are in a separate module
- **GIVEN** the `interfaces/tm_commands.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains the TM command handler logic

#### Scenario: Command functions are thin wrappers
- **GIVEN** any command function in `cli.py` (e.g., `translate`)
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 20 lines, delegating to functions in `orchestration.py` or `tm_commands.py`

### Requirement: Web UI frontend separation

The `web_ui.py` module SHALL contain only the Python API class (`Api`), `launch_ui`, `_UiHumanReviewer`, and `_PendingResult`. The embedded HTML/CSS/JS constant (`_HTML`) SHALL reside in a separate `web_frontend.py` module. `web_ui.py` SHALL import `_HTML` from `web_frontend.py`.

#### Scenario: web_ui.py does not contain HTML
- **GIVEN** the `interfaces/web_ui.py` file is inspected
- **WHEN** its content is searched for HTML tags (`<html>`, `<div>`, `<script>`)
- **THEN** no HTML tags are found; the `_HTML` constant is imported from `web_frontend.py`

#### Scenario: web_frontend.py contains the HTML constant
- **GIVEN** the `interfaces/web_frontend.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains the `HTML` string constant with the full embedded frontend

### Requirement: Shared config loader for CLI commands

The `interfaces/config_loader.py` module SHALL provide a `load_or_exit(path: Path | None = None) -> AppConfig` helper that wraps `load_config()`, prints a user-friendly error message on `ConfigError`, and calls `typer.Exit(1)`. All CLI command functions SHALL use this helper instead of duplicating the try/except/load pattern.

#### Scenario: Config loads successfully
- **GIVEN** a valid config.yaml at the default path
- **WHEN** `load_or_exit()` is called
- **THEN** an AppConfig is returned

#### Scenario: Config error exits gracefully
- **GIVEN** no config.yaml at the expected path
- **WHEN** `load_or_exit()` is called
- **THEN** a user-friendly error message is printed and `typer.Exit(1)` is called

#### Scenario: All CLI commands use the shared loader
- **GIVEN** the `cli.py` command functions are inspected
- **WHEN** their config-loading code is read
- **THEN** they all call `load_or_exit()` instead of duplicating try/except/load_config patterns

### Requirement: Adapters interface segregation

The `interfaces/models.py` module SHALL define `LLMAdapters` (containing `llm` and `embedder`) and `KnowledgeAdapters` (containing `glossary_index`, `persist_dir`, and `tm`) as separate dataclasses. The existing `Adapters` dataclass SHALL remain for backward compatibility but SHALL be composed of `LLMAdapters` and `KnowledgeAdapters`. Consumers SHALL depend on the narrowest interface they need.

#### Scenario: LLMAdapters contains only LLM-related adapters
- **GIVEN** the `LLMAdapters` dataclass is inspected
- **WHEN** its fields are listed
- **THEN** it contains `llm` and `embedder` only

#### Scenario: KnowledgeAdapters contains only knowledge-related adapters
- **GIVEN** the `KnowledgeAdapters` dataclass is inspected
- **WHEN** its fields are listed
- **THEN** it contains `glossary_index`, `persist_dir`, and `tm` only

#### Scenario: Adapters composes both
- **GIVEN** the `Adapters` dataclass is inspected
- **WHEN** its fields are listed
- **THEN** it contains all 5 fields (`llm`, `embedder`, `glossary_index`, `persist_dir`, `tm`) for backward compatibility

### Requirement: HITL review decomposition

The `human_review` function SHALL be decomposed into focused helpers: `_handle_review_decision(state, reviewed_text, cfg, *, llm) -> TranslationState` handles the approve/edit decision, `_re_audit_if_edited(state, edited_draft, cfg, *, llm) -> TranslationState` handles re-auditing. The public `human_review` function SHALL orchestrate these helpers and be ≤ 25 lines (excluding docstrings). The `llm` parameter SHALL be typed as `LLMEngineAdapter` and `tm` as `TranslationMemory` — not `object`.

#### Scenario: Reviewer approves without edits
- **GIVEN** a HumanReviewer that returns the original draft unchanged
- **WHEN** human_review is called
- **THEN** the state is returned with final_output set and no re-audit occurs

#### Scenario: Reviewer edits the draft
- **GIVEN** a HumanReviewer that returns an edited draft different from the original
- **WHEN** human_review is called
- **THEN** the correction is saved via _save_correction, the edited draft is re-audited via audit_node, and the state is updated

#### Scenario: Corrected pair is saved to TM
- **GIVEN** a reviewer edits the draft and a TranslationMemory is provided
- **WHEN** human_review is called
- **THEN** _save_to_tm inserts the corrected source-target pair into the TM

#### Scenario: human_review is ≤ 25 lines
- **GIVEN** the `human_review` function
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 25 lines, delegating to `_handle_review_decision` and `_re_audit_if_edited`

#### Scenario: llm parameter is typed as LLMEngineAdapter
- **GIVEN** the `human_review` function signature is inspected
- **WHEN** the type of the `llm` parameter is checked
- **THEN** it is typed as `LLMEngineAdapter`, not `object`

## MODIFIED Requirements

### Requirement: CLI dependency injection

The CLI SHALL construct concrete adapters via `_construct_adapters(cfg) -> Adapters`, which bundles `llm`, `embedder`, `glossary_index`, `persist_dir`, and `tm`. `_run_translation` and `_run_translation_streamed` accept these as keyword-only args for dependency injection (DIP). The `embedder` parameter SHALL be typed as `EmbeddingAdapter` and `tm` as `TranslationMemory` (or protocol) — not `object` or `object | None`.

#### Scenario: Adapters bundle contains all concrete adapters
- **GIVEN** a valid AppConfig
- **WHEN** _construct_adapters is called
- **THEN** an Adapters object is returned with llm, embedder, glossary_index, persist_dir, and tm fields

#### Scenario: embedder parameter is typed as EmbeddingAdapter
- **GIVEN** the `_run_translation` function signature is inspected
- **WHEN** the type of the `embedder` parameter is checked
- **THEN** it is typed as `EmbeddingAdapter`, not `object`

#### Scenario: tm parameter is typed as TranslationMemory
- **GIVEN** the `_run_translation` function signature is inspected
- **WHEN** the type of the `tm` parameter is checked
- **THEN** it is typed as `TranslationMemory` or a protocol, not `object | None`
