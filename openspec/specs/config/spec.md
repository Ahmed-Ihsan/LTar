## Purpose

Configuration loading and validation from `config.yaml` via Pydantic models. The config package provides the single source of runtime parameters for all components: model names, host URLs, filesystem paths, ChromaDB tuning, chunk parameters, TM threshold, and revision limits.
## Requirements
### Requirement: AppConfig top-level model

`AppConfig` SHALL be a Pydantic model that holds all runtime parameters loaded from `config.yaml`. It MUST embed `PathsConfig` and `ChromaConfig` sub-models plus model names, host URLs, chunk parameters, TM threshold, and revision limits. The `config.py` module SHALL NOT contain CLI command definitions — CLI logic SHALL live in a separate `cli.py` module within the config package. `load_config()` SHALL remain the single entry point for configuration loading and MUST NOT be called from within adapter constructors. The `llm_backend` field SHALL be typed as `Literal["ollama", "llamacpp", "gemini"]` with default `"ollama"` (offline-first). `AppConfig` SHALL additionally expose Gemini backend fields: `gemini_model: str = "gemini-2.0-flash"`, `gemini_embed_model: str = "text-embedding-004"`, `gemini_timeout: float = 120.0`, `gemini_rpm: int = 15`, and `gemini_api_key: str | None = None` (populated from the `GEMINI_API_KEY` environment variable by `load_config`, never from `config.yaml`). `gemini_timeout` SHALL be validated as a non-negative float. `gemini_rpm` SHALL be validated as a positive integer. An unknown `llm_backend` value SHALL fail Pydantic validation (raising `ConfigError` via `load_config`) with a message listing the three valid values.

#### Scenario: Load config from default path
- **GIVEN** a valid config.yaml at the default config path
- **WHEN** load_config is called with no path argument
- **THEN** an AppConfig is returned with all fields populated from the YAML file

#### Scenario: Load config from explicit path
- **GIVEN** a valid config.yaml at a custom path
- **WHEN** load_config is called with that path
- **THEN** an AppConfig is returned with fields from the specified file

#### Scenario: Config module does not contain CLI commands
- **GIVEN** the config package is inspected
- **WHEN** the modules are listed
- **THEN** `config.py` contains `load_config`, `AppConfig`, `ConfigError`, and `DEFAULT_CONFIG_PATH` only; CLI commands are in a separate module

#### Scenario: Adapters do not call load_config internally
- **GIVEN** an OllamaEngineAdapter, Embedder, or GeminiEngineAdapter is constructed
- **WHEN** the constructor is called
- **THEN** it receives model, host/timeout, and (for Gemini) api_key as keyword-only args and does NOT call `load_config()` internally

#### Scenario: llm_backend defaults to ollama
- **GIVEN** a config.yaml with no `llm_backend` key
- **WHEN** load_config parses it
- **THEN** `cfg.llm_backend == "ollama"` (offline-first default preserved)

#### Scenario: llm_backend accepts the three valid values
- **GIVEN** a config.yaml with `llm_backend: gemini`
- **WHEN** load_config parses it
- **THEN** `cfg.llm_backend == "gemini"` and the Gemini fields use their defaults when unset

#### Scenario: an unknown llm_backend is rejected
- **GIVEN** a config.yaml with `llm_backend: openai`
- **WHEN** load_config parses it
- **THEN** a `ConfigError` is raised with a message listing `ollama`, `llamacpp`, and `gemini` as the valid values

#### Scenario: Gemini fields default when the section is absent
- **GIVEN** a config.yaml with `llm_backend: gemini` and no `gemini_*` keys
- **WHEN** load_config parses it
- **THEN** `cfg.gemini_model == "gemini-2.0-flash"`, `cfg.gemini_embed_model == "text-embedding-004"`, `cfg.gemini_timeout == 120.0`, and `cfg.gemini_rpm == 15`

### Requirement: PathsConfig sub-model

`PathsConfig` SHALL be a Pydantic model holding filesystem paths: data_dir, corpus_dir, glossary_dir, raw_dir, db_dir, glossary_db, chroma_dir. Each path field SHALL have a Pydantic validator that ensures the path string is non-empty and normalized to the platform's path separator.

#### Scenario: PathsConfig fields are populated
- **GIVEN** a config.yaml with a `paths` section
- **WHEN** load_config parses it
- **THEN** the AppConfig.paths field is a PathsConfig with data_dir, corpus_dir, glossary_dir, raw_dir, db_dir, glossary_db, and chroma_dir set

#### Scenario: Empty path is rejected
- **GIVEN** a config.yaml with a `paths` section where `data_dir` is an empty string
- **WHEN** load_config parses it
- **THEN** a ConfigError is raised with a message indicating the field is empty

### Requirement: ChromaConfig sub-model

`ChromaConfig` SHALL be a Pydantic model holding ChromaDB HNSW tuning parameters: space, hnsw_M, construction_ef, search_ef. Each numeric field SHALL have a Pydantic validator that ensures the value is within an acceptable range (hnsw_M ≥ 2, construction_ef ≥ 1, search_ef ≥ 1).

#### Scenario: ChromaConfig fields are populated
- **GIVEN** a config.yaml with a `chroma` section
- **WHEN** load_config parses it
- **THEN** the AppConfig.chroma field is a ChromaConfig with space, hnsw_M, construction_ef, and search_ef set

#### Scenario: Invalid hnsw_M is rejected
- **GIVEN** a config.yaml with `chroma.hnsw_M` set to 0
- **WHEN** load_config parses it
- **THEN** a ConfigError is raised with a message indicating hnsw_M must be ≥ 2

### Requirement: ConfigError on invalid config

`ConfigError` SHALL be raised when config.yaml is missing, unreadable, or contains invalid values. `load_config` MUST validate the YAML structure and raise ConfigError with a descriptive message on failure.

#### Scenario: Missing config file
- **GIVEN** no config.yaml at the expected path
- **WHEN** load_config is called
- **THEN** a ConfigError is raised with a message indicating the file was not found

#### Scenario: Invalid YAML structure
- **GIVEN** a config.yaml with missing required fields
- **WHEN** load_config is called
- **THEN** a ConfigError is raised with a message indicating which field is invalid

### Requirement: Config Typer app

The config package SHALL expose a Typer `app` with a `load` command that loads and prints the parsed configuration. `DEFAULT_CONFIG_PATH` MUST define the default config file location. The Typer `app` and `load` command SHALL reside in a dedicated `cli.py` module within the config package, separate from `config.py` which contains loading logic only.

#### Scenario: Config load command prints parsed config
- **GIVEN** a valid config.yaml
- **WHEN** the Typer `load` command is executed
- **THEN** the parsed AppConfig is printed to stdout

#### Scenario: CLI module is separate from loading module
- **GIVEN** the config package is inspected
- **WHEN** `config.py` is read
- **THEN** it does not contain Typer app definitions or command decorators; those are in `cli.py`

### Requirement: ExcelConfig model

`ExcelConfig` SHALL be a Pydantic model in `src/config/models.py` with boolean toggles `translate_comments` (default `True`), `translate_headers_footers` (default `True`), `translate_chart_titles` (default `True`), `max_segment_chars` (default `4096`, segments longer than this are skipped with a warning), `max_xlsx_bytes` (default `104857600` = 100 MB, files larger than this are rejected before processing), and `max_segments` (default `10000`, workbooks whose extracted segment count exceeds this are rejected before translation). `AppConfig` SHALL expose it as `excel: ExcelConfig` with defaults applied when the `excel:` section is absent from `config.yaml`.

#### Scenario: defaults apply when the section is absent
- **GIVEN** a `config.yaml` with no `excel:` section
- **WHEN** `load_config` parses it
- **THEN** `cfg.excel.translate_comments` is `True`, `cfg.excel.translate_headers_footers` is `True`, `cfg.excel.translate_chart_titles` is `True`, `cfg.excel.max_segment_chars` is `4096`, `cfg.excel.max_xlsx_bytes` is `104857600`, and `cfg.excel.max_segments` is `10000`

#### Scenario: an oversized segment is skipped
- **GIVEN** a cell whose text exceeds `max_segment_chars`
- **WHEN** `translate_excel` runs
- **THEN** that segment is skipped (original text preserved) and a warning is recorded in the report

#### Scenario: an oversized workbook is rejected
- **GIVEN** a `config.yaml` with `excel.max_xlsx_bytes: 10485760` (10 MB) and an input workbook of 50 MB
- **WHEN** `translate_excel` runs
- **THEN** `InputValidationError` is raised before any adapter is constructed

#### Scenario: a workbook with too many segments is rejected
- **GIVEN** a `config.yaml` with `excel.max_segments: 1000` and a workbook whose extracted segment count is 1500
- **WHEN** `translate_excel` runs
- **THEN** `InputValidationError` is raised after extraction but before any translation

#### Scenario: invalid max_xlsx_bytes is rejected at config load
- **GIVEN** a `config.yaml` with `excel.max_xlsx_bytes: 0`
- **WHEN** `load_config` parses it
- **THEN** `ConfigError` is raised (the validator requires `max_xlsx_bytes >= 1_048_576`)

#### Scenario: invalid max_segments is rejected at config load
- **GIVEN** a `config.yaml` with `excel.max_segments: 50`
- **WHEN** `load_config` parses it
- **THEN** `ConfigError` is raised (the validator requires `max_segments >= 100`)

### Requirement: Config package structure

The configuration loader SHALL be split into a `src/config/` package with two modules: `config.py` (containing `AppConfig`, `load_config`, `ConfigError`, the Typer `app`, and `DEFAULT_CONFIG_PATH`) and `models.py` (containing `PathsConfig` and `ChromaConfig`). The `src/config/__init__.py` SHALL re-export the public API so that `from src.config import AppConfig, load_config, ConfigError, PathsConfig, ChromaConfig` works.

#### Scenario: Import AppConfig from config package
- **GIVEN** the refactored structure
- **WHEN** `from src.config import AppConfig` is executed
- **THEN** AppConfig is imported successfully via the package __init__ re-export

#### Scenario: Import PathsConfig from config models
- **GIVEN** the refactored structure
- **WHEN** `from src.config.models import PathsConfig` is executed
- **THEN** PathsConfig is imported successfully from the models submodule

#### Scenario: Import load_config from config package
- **GIVEN** the refactored structure
- **WHEN** `from src.config import load_config` is executed
- **THEN** load_config is imported successfully via the package __init__ re-export

#### Scenario: Old flat import path no longer exists
- **GIVEN** the refactored structure
- **WHEN** `from src.config import AppConfig` is executed (the old flat src/config.py is deleted)
- **THEN** the import succeeds because src/config/ is now a package with __init__.py re-exporting AppConfig

### Requirement: App entry point

A `src/app.py` module SHALL serve as the dependency-injection entry point that wires all components together. It SHALL expose a `main()` function used as the console script entry point. The `main()` function SHALL delegate to the CLI Typer app from `src.components.interfaces.cli`.

#### Scenario: Import main from app
- **GIVEN** the refactored structure
- **WHEN** `from src.app import main` is executed
- **THEN** main is imported successfully

#### Scenario: Console script uses app:main
- **GIVEN** the refactored pyproject.toml
- **WHEN** the `[project.scripts]` entry point is inspected
- **THEN** it specifies `iraqi-translate = "src.app:main"`

#### Scenario: app.py imports from all components
- **GIVEN** the refactored app.py
- **WHEN** its imports are inspected
- **THEN** it imports from `src.config`, `src.components.translation_pipeline`, `src.components.knowledge_sources`, `src.components.infrastructure`, and `src.components.interfaces` — never from old flat `src.*` paths

### Requirement: Pyproject package list update

`pyproject.toml` `[tool.setuptools]` packages SHALL be updated to include all new packages: `src`, `src.config`, `src.components`, `src.components.translation_pipeline`, `src.components.knowledge_sources`, `src.components.infrastructure`, `src.components.interfaces`.

#### Scenario: All packages listed in pyproject
- **GIVEN** the refactored pyproject.toml
- **WHEN** the `[tool.setuptools]` packages list is inspected
- **THEN** it includes src, src.config, src.components, and all four component subpackages

### Requirement: Ruff per-file-ignores path migration

All `[tool.ruff.lint.per-file-ignores]` entries SHALL be updated from old flat paths to new component paths:
- `src/prompts.py` → `src/components/translation_pipeline/prompts.py`
- `src/web_ui.py` → `src/components/interfaces/web_ui.py`
- `src/llm.py` → `src/components/infrastructure/llm.py`
- `src/cli.py` → `src/components/interfaces/cli.py`
- `src/graph.py` → `src/components/translation_pipeline/graph.py`
- `src/run_logging.py` → `src/components/infrastructure/run_logging.py`

#### Scenario: Ruff ignores point to new paths
- **GIVEN** the refactored pyproject.toml
- **WHEN** the `[tool.ruff.lint.per-file-ignores]` section is inspected
- **THEN** all paths reference the new component locations, not the old flat src/ paths

#### Scenario: Ruff check passes with zero errors
- **GIVEN** the refactored codebase
- **WHEN** `ruff check src/ tests/` is run
- **THEN** zero errors are reported

### Requirement: Old flat modules removed

After all content is migrated and imports updated, the 21 flat `src/*.py` modules SHALL be deleted: `config.py`, `state.py`, `graph.py`, `nodes.py`, `decision.py`, `prompts.py`, `exceptions.py`, `glossary.py`, `retrieval.py`, `tm.py`, `legal_search.py`, `ingestion.py`, `llm.py`, `embeddings.py`, `memory.py`, `run_logging.py`, `cli.py`, `web_ui.py`, `tk_ui.py`, `mcp_server.py`, `hitl.py`.

#### Scenario: No flat modules remain
- **GIVEN** the refactored src/ directory
- **WHEN** the top-level src/ directory is inspected
- **THEN** only `__init__.py`, `app.py`, `config/`, and `components/` exist — no flat .py modules

### Requirement: Test imports updated

All test files in `tests/` SHALL have their `from src.*` imports rewritten to the new component paths. The test suite SHALL pass with the same number of tests as the baseline — no tests lost, no new failures.

#### Scenario: All test imports use component paths
- **GIVEN** the refactored test suite
- **WHEN** any test file's imports are inspected
- **THEN** all `from src.*` imports reference component paths (e.g., `from src.components.translation_pipeline.models import TranslationState`), not old flat paths

#### Scenario: Test suite passes with no regressions
- **GIVEN** the refactored codebase
- **WHEN** `pytest --tb=short -q` is run
- **THEN** all tests pass and the test count matches the pre-refactor baseline

### Requirement: Mypy strict mode passes

The refactored codebase SHALL pass `mypy src/` with zero errors in strict mode, matching the pre-refactor baseline.

#### Scenario: Mypy strict passes
- **GIVEN** the refactored codebase
- **WHEN** `mypy src/` is run with strict = true
- **THEN** zero errors are reported

### Requirement: Gemini API key loaded from environment variable

`load_config` SHALL populate `AppConfig.gemini_api_key` by reading the `GEMINI_API_KEY` environment variable via `os.environ.get("GEMINI_API_KEY")`. The key SHALL NOT be read from `config.yaml` — if a `gemini_api_key` key appears in `config.yaml`, `load_config` SHALL raise `ConfigError` with a message stating that the Gemini API key must be provided via the `GEMINI_API_KEY` environment variable for security. When `llm_backend == "gemini"` and `GEMINI_API_KEY` is unset or empty, `load_config` SHALL raise `ConfigError` with a message instructing the user to export `GEMINI_API_KEY`. When `llm_backend != "gemini"`, an unset `GEMINI_API_KEY` SHALL NOT raise (the key is irrelevant on the Ollama path). The loaded `gemini_api_key` SHALL NEVER be written to logs, to the run log, or to any `__repr__` output (security — AGENTS.md §12).

#### Scenario: gemini backend with a valid env var succeeds
- **GIVEN** `llm_backend: gemini` in config.yaml and `GEMINI_API_KEY=AIza...` exported in the environment
- **WHEN** load_config parses it
- **THEN** `cfg.gemini_api_key == "AIza..."` and no error is raised

#### Scenario: gemini backend without the env var fails
- **GIVEN** `llm_backend: gemini` in config.yaml and `GEMINI_API_KEY` unset
- **WHEN** load_config parses it
- **THEN** a `ConfigError` is raised instructing the user to export `GEMINI_API_KEY`

#### Scenario: ollama backend with no env var succeeds
- **GIVEN** `llm_backend: ollama` in config.yaml and `GEMINI_API_KEY` unset
- **WHEN** load_config parses it
- **THEN** no error is raised and `cfg.gemini_api_key` is `None`

#### Scenario: a key placed in config.yaml is rejected
- **GIVEN** a config.yaml containing a `gemini_api_key: AIza...` entry
- **WHEN** load_config parses it
- **THEN** a `ConfigError` is raised stating the key must come from the `GEMINI_API_KEY` environment variable

#### Scenario: the API key is not logged
- **GIVEN** a loaded `AppConfig` with `gemini_api_key="AIza..."`
- **WHEN** the config is printed or logged (e.g. by the `config load` Typer command)
- **THEN** the `gemini_api_key` value is masked or omitted (never printed in cleartext)

