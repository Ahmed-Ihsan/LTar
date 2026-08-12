## MODIFIED Requirements

### Requirement: CLI dependency injection

The CLI SHALL construct concrete adapters via `_construct_adapters(cfg) -> Adapters`, which bundles `llm`, `embedder`, `glossary_index`, `persist_dir`, and `tm`. `_run_translation` and `_run_translation_streamed` accept these as keyword-only args for dependency injection (DIP). Variables holding adapter instances or store handles SHALL be annotated with concrete types (e.g., `ChromaStore`, `TranslationMemory`) not `object`, so that method calls like `.close()` and `.list_all()` pass mypy strict. `_construct_adapters` SHALL branch on `cfg.llm_backend`: when `cfg.llm_backend == "ollama"` (the default) it SHALL construct `OllamaEngineAdapter` and `Embedder` as today; when `cfg.llm_backend == "gemini"` it SHALL construct a single `GeminiEngineAdapter` and use it for **both** the `llm` and `embedder` fields of `Adapters` (the Gemini backend serves LLM and embeddings from the same provider). When `cfg.llm_backend == "gemini"` and `cfg.gemini_api_key` is `None`, `_construct_adapters` SHALL exit with a clear error (this is a defensive check; `load_config` already rejects this case). The `google-genai` SDK SHALL be lazily imported inside `gemini.py` so the Ollama code path never imports it.

#### Scenario: Adapters bundle contains all concrete adapters
- **GIVEN** a valid AppConfig with `llm_backend: ollama`
- **WHEN** _construct_adapters is called
- **THEN** an Adapters object is returned with llm, embedder, glossary_index, persist_dir, and tm fields

#### Scenario: Adapter variables have concrete types
- **GIVEN** the refactored cli.py with concrete type annotations
- **WHEN** mypy checks method calls on adapter variables (e.g., store.close(), tm.list_all())
- **THEN** no attr-defined errors are reported because the variables are typed with their concrete classes

#### Scenario: gemini backend constructs a GeminiEngineAdapter for both llm and embedder
- **GIVEN** a valid AppConfig with `llm_backend: gemini` and a non-None `gemini_api_key`
- **WHEN** `_construct_adapters` is called
- **THEN** the returned `Adapters.llm` and `Adapters.embedder` are the **same** `GeminiEngineAdapter` instance (single backend serving both roles)

#### Scenario: ollama backend path is unchanged
- **GIVEN** a valid AppConfig with `llm_backend: ollama`
- **WHEN** `_construct_adapters` is called
- **THEN** it constructs `OllamaEngineAdapter` and `Embedder` exactly as before this change (no behavioral regression)

#### Scenario: gemini backend without an API key exits with a clear error
- **GIVEN** a valid AppConfig with `llm_backend: gemini` and `gemini_api_key is None`
- **WHEN** `_construct_adapters` is called
- **THEN** it prints an error naming `GEMINI_API_KEY` and raises `typer.Exit(code=1)` without constructing any adapter

#### Scenario: the google-genai SDK is not imported on the ollama path
- **GIVEN** `llm_backend: ollama`
- **WHEN** `_construct_adapters` runs and `sys.modules` is inspected
- **THEN** `google.genai` is NOT present in `sys.modules` (lazy import is confined to `gemini.py`)

### Requirement: CLI subcommands

The CLI SHALL be a Typer application with nine subcommands: `doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, `ui`, and `excel`. Each command accepts its arguments via Typer options and arguments and lives in its own module under `src/components/interfaces/commands/`. `cli.py` SHALL be a thin Typer app that imports and registers the commands; it SHALL NOT contain command logic directly. Each command SHALL be decorated with `handle_pipeline_errors` from `src/utils/cli_errors.py` so exit codes are consistent (see the `cli-commands` capability for the exit-code table). The `translate`, `batch`, and `excel` commands SHALL validate every user-supplied `--input` and `--out` path via `src.utils.paths.validate_path_in_root` against the project root before any file operation; on `PathContainmentError` they SHALL exit with code 4. Domain exceptions from the Gemini backend (`GeminiAuthError`, `GeminiQuotaError`, `LLMConnectionError`, `LLMTimeoutError`) SHALL map to the same CLI exit codes as the Ollama connection/timeout family (connection → 2, other domain → 1) via the existing `handle_pipeline_errors` decorator — no new exit code is introduced.

#### Scenario: doctor runs environment diagnostics
- **GIVEN** the CLI is invoked with the `doctor` subcommand
- **WHEN** the command executes
- **THEN** it checks the configured backend's reachability, model presence (for local backends) or API-key presence + connectivity (for `gemini`), ChromaDB directory, glossary DB, TM DB, and RAM headroom (for local backends), printing a CheckResult for each

#### Scenario: translate translates a single text
- **GIVEN** the CLI is invoked with `translate --input "المادة ١" --direction ar-en`
- **WHEN** the command executes
- **THEN** the translation pipeline runs and the final translation is printed

#### Scenario: batch translates a JSONL file sequentially
- **GIVEN** the CLI is invoked with `batch --input translations.jsonl`
- **WHEN** the command executes
- **THEN** each line of the JSONL file is translated sequentially (concurrency = 1) and results are written to the output file

#### Scenario: ingest builds the vector store and glossary
- **GIVEN** the CLI is invoked with `ingest --rebuild`
- **WHEN** the command executes
- **THEN** the corpus is parsed, chunked, embedded, and written to ChromaDB, and the glossary is loaded into SQLite

#### Scenario: tm-build builds TM from corpus
- **GIVEN** the CLI is invoked with `tm-build`
- **WHEN** the command executes
- **THEN** the Translation Memory is built from aligned corpus files

#### Scenario: ui launches the configured desktop UI
- **GIVEN** the CLI is invoked with `ui`
- **WHEN** the command executes
- **THEN** the desktop UI backend selected by `cfg.ui.backend` (default `"web"`) is launched

#### Scenario: cli.py is a thin registration file
- **GIVEN** the `cli.py` source
- **WHEN** its line count and imports are inspected
- **THEN** it imports each command from `src.components.interfaces.commands.*` and registers it; it contains no command logic definitions

#### Scenario: a Gemini auth error maps to exit code 2
- **GIVEN** the pipeline raises `GeminiAuthError` during a `translate` run with `llm_backend: gemini`
- **WHEN** `handle_pipeline_errors` catches it
- **THEN** the CLI exits with code 2 (connection/auth family), matching the Ollama connection-error exit code

## ADDED Requirements

### Requirement: Doctor command Gemini connectivity check

The `doctor` command SHALL branch on `cfg.llm_backend`. When `cfg.llm_backend == "gemini"`, it SHALL run a `_check_gemini_api_key(cfg) -> CheckResult` check (verifying `cfg.gemini_api_key` is non-None and non-empty) and a `_check_gemini_reachable(cfg) -> CheckResult` check (constructing a `GeminiEngineAdapter` and issuing a minimal API ping — e.g., listing available models — to verify the key is valid and the API is reachable). It SHALL skip the Ollama-reachability, local-model-presence, and LLM-RAM-budget checks (those are local-backend concerns; cloud inference does not consume local RAM for weights). It SHALL still run the ChromaDB-directory, glossary-DB, TM-DB, and (general) RAM-headroom checks — those are backend-independent. The two new check helpers SHALL reside in `src/components/interfaces/diagnostics.py` alongside the existing `_check_*` helpers. A failed API-key or connectivity check SHALL cause the doctor command to exit with code 2 (matching the Ollama-failed exit code).

#### Scenario: doctor checks the API key when gemini is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: gemini` in config.yaml
- **WHEN** the command executes
- **THEN** a CheckResult named "Gemini API key present" is rendered, OK only when `cfg.gemini_api_key` is non-empty

#### Scenario: doctor pings the Gemini API when gemini is selected
- **GIVEN** the CLI is invoked with `doctor`, `llm_backend: gemini`, and a valid `GEMINI_API_KEY`
- **WHEN** the command executes
- **THEN** a CheckResult named "Gemini API reachable" is rendered, OK only when the list-models ping succeeds

#### Scenario: doctor skips Ollama checks when gemini is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: gemini`
- **WHEN** the rendered checks are inspected
- **THEN** no CheckResult named "Ollama daemon reachable" or "Required models present" appears (those checks are skipped on the gemini path)

#### Scenario: doctor still checks ChromaDB, glossary, and TM when gemini is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: gemini`
- **WHEN** the rendered checks are inspected
- **THEN** the "ChromaDB directory exists", "Glossary SQLite populated", and TM checks still appear (they are backend-independent)

#### Scenario: a failed Gemini connectivity check exits with code 2
- **GIVEN** the CLI is invoked with `doctor`, `llm_backend: gemini`, and an invalid `GEMINI_API_KEY`
- **WHEN** the "Gemini API reachable" check fails
- **THEN** the doctor command exits with code 2

#### Scenario: doctor runs Ollama checks when ollama is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: ollama`
- **WHEN** the command executes
- **THEN** the existing Ollama reachability, model-presence, and RAM-headroom checks run exactly as before this change (no behavioral regression)
