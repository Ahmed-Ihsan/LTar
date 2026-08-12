## 1. Fix `requirements.txt`

- [x] 1.1 Add `pywebview>=5.0,<7` to `requirements.txt` (matches `pyproject.toml`)
- [x] 1.2 Move `gradio>=4.0,<5` to a comment-annotated "Optional dependencies (not required for CLI or desktop UI)" section at the bottom of `requirements.txt`, commented out with a note explaining how to install it
- [x] 1.3 Sort dependencies alphabetically within each section
- [x] 1.4 Verify: `pip install -r requirements.txt` succeeds and `python -c "import webview"` works
- [x] 1.5 Verify: `python -c "import gradio"` fails (it is now optional/commented) — document that users who want gradio must uncomment it

## 2. Reconcile `pyproject.toml`

- [x] 2.1 Grep the codebase for 3.11-only features: `from typing import Self`, `ExceptionGroup`, `tomllib`, `match` statements on custom classes. Record findings.
- [x] 2.2 If NO 3.11-only features are found: change `requires-python = ">=3.11,<3.12"` to `requires-python = ">=3.10,<3.12"` and update README to say "Python 3.10 or 3.11"
- [x] 2.3 If 3.11-only features ARE found: keep the pin at `>=3.11,<3.12` and update README to say "Python 3.11 required (3.10 is not supported because the code uses <feature>)" — N/A (no 3.11-only features found; task 2.2 path taken)
- [x] 2.4 Replace every `ARCHITECTURE.md` reference in `pyproject.toml` comments with `AGENTS.md`
- [x] 2.5 Replace every `PROMPTS.md` reference in `pyproject.toml` comments with `src/components/translation_pipeline/prompts.py`
- [x] 2.6 Ensure `gradio` is in `[project.optional-dependencies]` (it already is) and document that `requirements.txt` lists it commented-out for convenience
- [x] 2.7 Verify: `pip install -e .` succeeds; `python -c "import src.app"` works
- [x] 2.8 Verify: `pip install -e .[gradio]` succeeds and `python -c "import gradio"` works

## 3. Update `openspec/config.yaml`

- [x] 3.1 Change the model name in the `context` block from `qwen2.5:7b-instruct-q5_K_M` to `gemma3:4b`
- [x] 3.2 Add a note in the context block: "Alternative: `qwen2.5:7b-instruct-q5_K_M` also fits the 8 GB RAM ceiling; `config.yaml` is the runtime source of truth."
- [x] 3.3 Verify: `openspec validate --all` passes (config.yaml change does not affect spec validation, but check anyway)

## 4. Update `README.md`

- [x] 4.1 Fix the Python version statement in §2 (Setup/Requirements) to match the reconciled pin from task 2.2 or 2.3
- [x] 4.2 Add a "Dependencies" subsection in §5 (Installation) noting that `requirements.txt` is the canonical install list and `pyproject.toml` is for editable installs (`pip install -e .`)
- [x] 4.3 Document the optional `gradio` dependency: "gradio is optional and not required for the CLI or desktop UI. To install it, uncomment the line in `requirements.txt` or run `pip install -e .[gradio]`."
- [x] 4.4 Verify: README §2 and §5 are internally consistent (no contradiction between Python version and install instructions)

## 5. Archive the three completed OpenSpec changes

- [x] 5.1 Run `openspec validate refactor-to-component-architecture` — must pass before archiving
- [x] 5.2 Run `openspec archive refactor-to-component-architecture`
- [x] 5.3 Run `openspec validate --all` — must pass after the archive
- [x] 5.4 Run `openspec validate solid-clean-code-refactor` — must pass
- [x] 5.5 Run `openspec archive solid-clean-code-refactor`
- [x] 5.6 Run `openspec validate --all` — must pass
- [x] 5.7 Run `openspec validate fix-mypy-strict-errors` — must pass
- [x] 5.8 Run `openspec archive fix-mypy-strict-errors`
- [x] 5.9 Run `openspec validate --all` — must pass
- [x] 5.10 Run `openspec list` — should show no active changes (all three archived)
- [x] 5.11 Run `openspec list --specs` — should show the merged specs with updated requirement counts

## 6. Final verification

- [x] 6.1 Run `pip install -r requirements.txt` in a fresh venv — must succeed and `iraqi-translate doctor` must run
- [x] 6.2 Run `pip install -e .` in a fresh venv — must succeed and `iraqi-translate doctor` must run
- [x] 6.3 Run `ruff check src/ tests/` — must be clean
- [x] 6.4 Run `mypy src/` — must not introduce new errors
- [x] 6.5 Run `pytest --tb=short -q` — full suite green (excluding `slow`)
- [x] 6.6 Run `openspec validate --all` — must pass
- [x] 6.7 Run `openspec doctor` — should report a healthy root
- [x] 6.8 Verify: `ARCHITECTURE.md` and `PROMPTS.md` are NOT referenced anywhere in `pyproject.toml` (grep confirms zero matches)
- [x] 6.9 Verify: `openspec/config.yaml` model name matches `config.yaml` model name
