## Purpose

Structured application-level logging shared by every component. This
capability exists so that adapter errors, retries, swallowed exceptions,
and HTTP failures are visible to anyone debugging a failed run —
`RunLogger` records *what the graph did*, while `application-logging`
records *what the infrastructure did*. It lives in `src/utils/` (same
leaf package as `input-validation`) so every component can import it
without creating a circular dependency.

## ADDED Requirements

### Requirement: Logging configuration entry point

`src/utils/logging_setup.py` SHALL expose `configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None` that installs a `logging.StreamHandler` writing to stderr with format `%(asctime)s %(levelname)s %(name)s %(message)s`, and — when `log_dir` is provided — a `logging.FileHandler` writing to `<log_dir>/app.log`. The function SHALL be idempotent: repeated calls SHALL NOT install duplicate handlers (it SHALL clear existing handlers on the root logger before installing). Every component module SHALL create its own `logger = logging.getLogger(__name__)` at module top; no module SHALL use the root logger directly for emission.

#### Scenario: configure_logging installs a stderr handler
- **GIVEN** a fresh process with no logging configured
- **WHEN** `configure_logging(level="INFO")` is called
- **THEN** the root logger has exactly one `StreamHandler` whose stream is stderr, and `logging.getLogger("any.module").info("x")` prints a formatted line to stderr

#### Scenario: configure_logging installs a file handler when log_dir is provided
- **GIVEN** a fresh process and a writable `log_dir`
- **WHEN** `configure_logging(level="INFO", log_dir=log_dir)` is called
- **THEN** the root logger has a `StreamHandler` (stderr) and a `FileHandler` writing to `<log_dir>/app.log`, and a logged record appears in both

#### Scenario: configure_logging is idempotent
- **GIVEN** `configure_logging()` has already been called once
- **WHEN** `configure_logging()` is called a second time
- **THEN** the root logger still has exactly one `StreamHandler` (and one `FileHandler` if `log_dir` was provided) — no duplicate handlers are installed

#### Scenario: per-module loggers emit under their module name
- **GIVEN** `configure_logging()` has been called and a module `src.components.infrastructure.llm` has `logger = logging.getLogger(__name__)`
- **WHEN** `logger.warning("timeout")` is called
- **THEN** the emitted line contains `src.components.infrastructure.llm WARNING timeout`
