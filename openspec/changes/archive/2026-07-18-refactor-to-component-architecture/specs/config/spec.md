## ADDED Requirements

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
