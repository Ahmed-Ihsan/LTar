## Purpose

Build, packaging, and dependency-management rules for the Iraqi Legal
Translation Agent. This capability documents the contract between the
two install paths (`pip install -r requirements.txt` and
`pip install -e .`), the Python version requirement, and the
OpenSpec hygiene rules (archiving completed changes, keeping
`openspec/config.yaml` consistent with `config.yaml`). It exists so
that a new contributor can produce a working environment from either
install path and so that the source-of-truth specs reflect the
architecture that exists in `src/components/`.

## ADDED Requirements

### Requirement: Canonical install paths SHALL agree

`requirements.txt` SHALL be the canonical install list for `pip install -r requirements.txt` (the documented install path in `README.md`). `pyproject.toml` `[project.dependencies]` SHALL mirror `requirements.txt` for `pip install -e .` so that both install paths produce the same runtime environment. Optional dependencies (e.g., `gradio`) SHALL be listed in `pyproject.toml` under `[project.optional-dependencies]` AND in a comment-annotated optional section at the bottom of `requirements.txt` (commented out, with a note explaining how to install them). Every runtime dependency listed in `pyproject.toml` SHALL also appear (uncommented) in `requirements.txt`, and vice versa.

#### Scenario: pywebview is present in both install paths
- **GIVEN** the project's `requirements.txt` and `pyproject.toml`
- **WHEN** a user runs `pip install -r requirements.txt` in a fresh venv
- **THEN** `python -c "import webview"` succeeds (pywebview is installed)

#### Scenario: pip install -e . produces the same runtime environment
- **GIVEN** the project's `pyproject.toml`
- **WHEN** a user runs `pip install -e .` in a fresh venv
- **THEN** `python -c "import webview"` succeeds (pywebview is installed, mirroring `requirements.txt`)

#### Scenario: gradio is optional in both install paths
- **GIVEN** the project's `requirements.txt` and `pyproject.toml`
- **WHEN** a user runs `pip install -r requirements.txt` (without uncommenting the optional section)
- **THEN** `python -c "import gradio"` fails (gradio is not installed by default)
- **WHEN** a user runs `pip install -e .[gradio]`
- **THEN** `python -c "import gradio"` succeeds

### Requirement: Python version pin SHALL match the codebase and README

`pyproject.toml` `requires-python` SHALL match the Python features actually used by the codebase and the Python version documented in `README.md` §2. If the codebase uses 3.11-only features (`typing.Self`, `ExceptionGroup`, `tomllib`, `match` on custom classes), the pin SHALL be `>=3.11,<3.12` and `README.md` SHALL state "Python 3.11 required." If no 3.11-only features are used, the pin SHALL be `>=3.10,<3.12` and `README.md` SHALL state "Python 3.10 or 3.11." The two documents SHALL NOT contradict each other.

#### Scenario: the pin and README agree
- **GIVEN** `pyproject.toml` and `README.md`
- **WHEN** the `requires-python` pin and the README §2 Python version statement are compared
- **THEN** they agree (both say 3.10+, or both say 3.11+)

#### Scenario: the pin reflects the codebase
- **GIVEN** the codebase under `src/`
- **WHEN** it is grepped for 3.11-only features
- **THEN** the `requires-python` pin is consistent with the findings (3.11-only features present → pin is `>=3.11`; none present → pin is `>=3.10`)

### Requirement: Stale file references SHALL be removed

`pyproject.toml` comments SHALL NOT reference files that do not exist in the repository. In particular, references to `ARCHITECTURE.md` SHALL be replaced with `AGENTS.md` (the canonical architecture guide), and references to `PROMPTS.md` SHALL be replaced with `src/components/translation_pipeline/prompts.py` (the canonical prompt source).

#### Scenario: no reference to ARCHITECTURE.md
- **GIVEN** `pyproject.toml`
- **WHEN** it is grepped for `ARCHITECTURE.md`
- **THEN** zero matches are found

#### Scenario: no reference to PROMPTS.md
- **GIVEN** `pyproject.toml`
- **WHEN** it is grepped for `PROMPTS.md`
- **THEN** zero matches are found

### Requirement: Completed OpenSpec changes SHALL be archived

When an OpenSpec change has all tasks complete (`openspec status --change <name>` reports 4/4 artifacts complete and every task in `tasks.md` is checked), it SHALL be archived via `openspec archive <name>` so its delta specs merge into `openspec/specs/` and the change moves to `openspec/changes/archive/`. The `openspec/changes/` directory SHALL NOT contain completed-but-unarchived changes.

#### Scenario: no completed changes linger in changes/
- **GIVEN** the `openspec/changes/` directory
- **WHEN** `openspec list` is run
- **THEN** every change listed is either in-progress (not all tasks complete) or newly created; no change shows "✓ Complete" status

#### Scenario: archived changes are in archive/
- **GIVEN** the three completed changes (`refactor-to-component-architecture`, `solid-clean-code-refactor`, `fix-mypy-strict-errors`)
- **WHEN** the archive operation has run
- **THEN** each change directory exists under `openspec/changes/archive/` and its delta specs have been merged into `openspec/specs/`

### Requirement: openspec/config.yaml SHALL match config.yaml

`openspec/config.yaml`'s `context` block SHALL reference the same default LLM model as `config.yaml` (the runtime source of truth). If `config.yaml` uses `gemma3:4b`, `openspec/config.yaml` SHALL also reference `gemma3:4b`, with a note that alternative models (e.g., `qwen2.5:7b-instruct-q5_K_M`) also fit the RAM ceiling.

#### Scenario: openspec/config.yaml model name matches config.yaml
- **GIVEN** `config.yaml` and `openspec/config.yaml`
- **WHEN** their default model names are compared
- **THEN** they are identical (both `gemma3:4b`)
