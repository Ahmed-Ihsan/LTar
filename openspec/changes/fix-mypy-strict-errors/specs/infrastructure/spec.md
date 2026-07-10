## MODIFIED Requirements

### Requirement: System memory and RAM guard

`read_memory_info() -> MemoryInfo | None` SHALL read total and available system RAM. `available_ram_gb() -> float | None` returns available RAM in GiB. `check_ram_guard(min_gb: float = RAM_GUARD_MIN_GB) -> None` raises `RAMGuardError` if available RAM is below the threshold. `RAM_GUARD_MIN_GB` = 1.5. `MemoryInfo` is a dataclass with total_bytes and available_bytes. The `MEMORYSTATUSEX` ctypes Structure in `_read_memory_info_windows` SHALL annotate `_fields_` with a type that satisfies mypy strict mode (the base `Structure._fields_` type from ctypes is incompatible with `list[tuple[str, object]]`; a targeted `# type: ignore[misc,assignment]` SHALL be used with a comment explaining the ctypes limitation). The `ctypes.windll.kernel32.GlobalMemoryStatusEx` call SHALL use a `# type: ignore[attr-defined]` comment that is actually needed (stale comments SHALL be removed). The module SHALL declare `__all__` listing all re-exported symbols including `MemoryInfo` so that mypy's `--no-implicit-reexport` does not flag imports from this module.

#### Scenario: RAM guard passes with sufficient memory
- **GIVEN** available RAM is 3.0 GB and min_gb is 1.5
- **WHEN** check_ram_guard is called
- **THEN** no exception is raised

#### Scenario: RAM guard fails with insufficient memory
- **GIVEN** available RAM is 1.0 GB and min_gb is 1.5
- **WHEN** check_ram_guard is called
- **THEN** a RAMGuardError is raised

#### Scenario: read_memory_info returns None on unsupported platform
- **GIVEN** a platform where memory reading is not supported
- **WHEN** read_memory_info is called
- **THEN** None is returned (no crash)

#### Scenario: MEMORYSTATUSEX _fields_ passes mypy strict
- **GIVEN** the refactored memory.py with the _fields_ annotation
- **WHEN** `mypy src/` is run in strict mode
- **THEN** no errors are reported for the _fields_ assignment (the type-ignore comment covers the ctypes base-class incompatibility)

#### Scenario: MemoryInfo is explicitly re-exported
- **GIVEN** the refactored memory.py with __all__ declared
- **WHEN** another module imports `MemoryInfo` from `src.components.infrastructure.memory`
- **THEN** mypy does not report an `attr-defined` error because MemoryInfo is listed in `__all__`

### Requirement: Structured run logging

`RunLogger` SHALL write JSON lines per node execution to a JSONL file. It is constructed with `(log_dir, run_id)`, exposes `run_id` and `path` properties, and has a `log_node(node_name, latency_ms, state)` method. It supports context manager protocol (`__enter__`/`__exit__`) and a `close()` method. Stale `# type: ignore` comments that are no longer needed under the current mypy version SHALL be removed. The `datetime.now(timezone.utc)` call SHALL keep the `# noqa: UP017` ruff comment (Python 3.10 compatibility) but SHALL NOT have a mypy `# type: ignore` comment if mypy does not flag it.

#### Scenario: RunLogger writes one JSON line per node
- **GIVEN** a RunLogger with a valid log_dir and run_id
- **WHEN** log_node is called with node_name="translate", latency_ms=1500, and a TranslationState
- **THEN** one JSON line is appended to the log file containing the node name, latency, and state snapshot

#### Scenario: RunLogger as context manager
- **GIVEN** a RunLogger used in a `with` statement
- **WHEN** the context exits
- **THEN** the file handle is closed automatically via __exit__

#### Scenario: RunLogger path property
- **GIVEN** a RunLogger with log_dir="logs/" and run_id="abc123"
- **WHEN** the path property is accessed
- **THEN** it returns the full path to the JSONL log file

#### Scenario: RunLogger passes mypy strict with no stale type-ignores
- **GIVEN** the refactored run_logging.py
- **WHEN** `mypy src/` is run in strict mode
- **THEN** no `unused-ignore` errors are reported for run_logging.py
