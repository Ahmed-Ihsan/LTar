# AGENTS.md — Iraqi Legal Translation Agent

Project-specific guidance for any agent working in this repo.

## Environment (this host)

- The project targets Python `>=3.11,<3.12` (see `pyproject.toml`), but the
  host has no Python 3.11. A Python 3.10 venv with all deps installed lives at
  `.venv310/`. **Always use `.venv310\Scripts\python.exe`** to run tests/tools:
  ```powershell
  .\.venv310\Scripts\python.exe -m pytest tests/ -q
  .\.venv310\Scripts\python.exe -m ruff check <files>
  ```
- PowerShell is the shell. Do **not** use `&&` to chain commands — use `;`.
- `py -3.11` is not available; `py -3.10` lacks the deps (langgraph etc.).

## Verification commands

- Full suite: `.\.venv310\Scripts\python.exe -m pytest tests/ -q`
  - Expected: ~192 passed, 3 deselected (the 3 `@pytest.mark.slow` real-Ollama
    tests need a running daemon and are excluded from the default run).
- Lint: `.\.venv310\Scripts\python.exe -m ruff check <changed files>`
  - NOTE: several pre-existing untouched files (e.g. `tests/test_retrieval.py`)
    have ruff errors (unused imports). Only lint the files you changed.
- No `mypy`/`radon` are wired into a CI gate here; ruff is the gate.
- TM build: `.\.venv310\Scripts\python.exe -m src.cli tm-build`
  - Builds `db/tm.sqlite` from `data/corpus` aligned ar/en article pairs.

## Architecture / conventions (enforced by `.devin/skills/*`)

- **Adapter boundary**: engine exceptions (`ollama.ResponseError`,
  `httpx.*`) are caught inside adapters (`src/llm.py`, `src/embeddings.py`) and
  re-raised as domain exceptions from `src/exceptions.py`. Nodes and the CLI
  only ever see domain exceptions.
- **Dependency injection**: the CLI (`src/cli.py`) is the only place concrete
  adapters are constructed (engineering-principles §3.6). `run_translation` /
  `run_translation_streamed` are the orchestration seams; tests inject
  `mock_llm` / `mock_embedder` / in-memory `GlossaryIndex` / temp ChromaDB
  (testing-verification §3.4) — no Ollama daemon, no network in CI.
- **OCP**: node functions in `src/nodes.py` are closed for modification; new
  cross-cutting concerns (logging, etc.) are added at the orchestration seam
  (`src/graph.py` / `src/cli.py`).
- **Single source of truth**: `src/memory.py` owns system-memory reading
  (`MemoryInfo`, `read_memory_info`, `check_ram_guard`); both `src/cli.py`
  (doctor) and `src/llm.py` (RAM guard) import from it.

## CLI exit codes (task 4.3 hardening)

- `0` — success.
- `1` — generic error (config, missing file, empty input, translation error).
- `2` — Ollama daemon unreachable (`OllamaConnectionError` /
  `EmbeddingConnectionError`).
- `3` — RAM guard abort (`RAMGuardError`, < 1.5 GB free before an LLM call).

## Structured logging (task 4.3.1)

- `src/run_logging.py::RunLogger` writes `logs/run_<run_id>.jsonl` (one JSON
  line per node execution). `run_id` defaults to a UTC timestamp.
- The CLI `translate` / `batch` / `ui` commands auto-create a `RunLogger`
  pointing at `<project_root>/logs`. The seam is opt-in: passing
  `run_logger=None` (the default) runs the pipeline with no logging.

## LangGraph gotcha

- `StateGraph.add_node` calls `get_type_hints(action)`. If you wrap a node
  callable with `functools.wraps`, the copied string annotations are evaluated
  against the wrapper's globals and can raise `NameError`. Wrap nodes with an
  **annotation-free** inner function (see `_wrap_with_logging` in `src/graph.py`).
- The Auditor node is named `"auditor"` (not `"audit"`) because LangGraph 0.2.x
  forbids a node name that collides with a state key (`audit` is a state field).
