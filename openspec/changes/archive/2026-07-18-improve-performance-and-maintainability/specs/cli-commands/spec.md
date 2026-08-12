## Purpose

Per-command modules split out of `cli.py` for single-responsibility and
independent testability. Each CLI subcommand (`doctor`, `translate`,
`batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`,
`ui`, `excel`) lives in its own module under
`src/components/interfaces/commands/` and owns its argument parsing,
adapter construction, error handling, and output rendering. `cli.py`
becomes a thin Typer app that imports and registers the commands. This
capability exists so that adding or editing a single command does not
require touching a 539-line `cli.py`.

## ADDED Requirements

### Requirement: Per-command module structure

Each CLI subcommand SHALL live in its own module under `src/components/interfaces/commands/`: `doctor.py`, `translate.py`, `batch.py`, `ingest.py`, `tm_build.py`, `tm_add.py`, `ui.py`, `excel.py`. Each command module SHALL own its argument parsing (Typer options and arguments), adapter construction (via `_construct_adapters` or a shared helper), error handling (via the `handle_pipeline_errors` decorator from `src/utils/cli_errors.py`), and output rendering. `cli.py` SHALL be a thin Typer app that imports the command modules and registers their `@app.command()` entries; it SHALL NOT contain command logic directly.

#### Scenario: cli.py is a thin registration file
- **GIVEN** the `cli.py` source
- **WHEN** its line count and imports are inspected
- **THEN** it imports each command from `src.components.interfaces.commands.*` and registers it via `app.command()`; it contains no `def translate(...)`, `def batch(...)`, etc. definitions

#### Scenario: each command module is independently importable
- **GIVEN** the `commands/translate.py` module
- **WHEN** it is imported in isolation
- **THEN** it imports successfully and exposes a `register(app: typer.Typer) -> None` function (or a Typer command object) without side effects

#### Scenario: the CLI surface is unchanged
- **GIVEN** the refactored CLI
- **WHEN** `iraqi-translate --help` is run
- **THEN** all eight subcommands (`doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, `ui`) plus `excel` are listed with the same arguments and help text as before the refactor

### Requirement: Shared CLI error-handling decorator

`src/utils/cli_errors.py` SHALL expose a `handle_pipeline_errors` decorator that catches `OllamaConnectionError` and `EmbeddingConnectionError` (printing a connection error and exiting with code 2), `RAMGuardError` (printing a RAM-guard message and exiting with code 3), `PathContainmentError` (printing a path-containment error and exiting with code 4), `InputValidationError` (printing a validation error and exiting with code 5), `OSError` (printing an I/O error and exiting with code 6), and any other `Exception` (printing a generic error and exiting with code 1). Every CLI command SHALL be decorated with `handle_pipeline_errors` so exit codes are consistent across commands.

#### Scenario: a RAM-guard error exits with code 3 from any command
- **GIVEN** any CLI command decorated with `handle_pipeline_errors` and a pipeline that raises `RAMGuardError`
- **WHEN** the command runs
- **THEN** a RAM-guard message is printed and the process exits with code 3

#### Scenario: an Ollama connection error exits with code 2 from any command
- **GIVEN** any CLI command decorated with `handle_pipeline_errors` and a pipeline that raises `OllamaConnectionError`
- **WHEN** the command runs
- **THEN** a connection error message is printed and the process exits with code 2

#### Scenario: a generic error exits with code 1 from any command
- **GIVEN** any CLI command decorated with `handle_pipeline_errors` and a pipeline that raises an unexpected `RuntimeError`
- **WHEN** the command runs
- **THEN** a generic error message is printed and the process exits with code 1

### Requirement: Standardized CLI exit codes

The CLI SHALL use a standardized exit-code table: 0 = success, 1 = generic error, 2 = Ollama/embedding connection error, 3 = RAM guard error, 4 = path-containment violation, 5 = JSONL validation error, 6 = I/O error. The table SHALL be documented in `AGENTS.md` §11. Every command (`doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, `ui`, `excel`) SHALL use the appropriate code from this table; no command SHALL use exit code 1 for a connection or RAM-guard error.

#### Scenario: doctor uses exit code 2 for Ollama connection failure
- **GIVEN** the `doctor` command and an unreachable Ollama daemon
- **WHEN** `iraqi-translate doctor` runs
- **THEN** it prints a connection error and exits with code 2 (not 1)

#### Scenario: ingest uses exit code 3 for RAM guard
- **GIVEN** the `ingest` command and a pipeline that raises `RAMGuardError`
- **WHEN** `iraqi-translate ingest` runs
- **THEN** it prints a RAM-guard message and exits with code 3 (not 1)

#### Scenario: the exit-code table is documented
- **GIVEN** `AGENTS.md` §11
- **WHEN** it is inspected
- **THEN** it contains a table listing codes 0–6 with their meanings
