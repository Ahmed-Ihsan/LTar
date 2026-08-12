## Why

A production-grade audit (2026-07-18) found that the project's build
configuration and OpenSpec state have drifted from reality. Four
Critical and two High findings:

1. **`pywebview` is missing from `requirements.txt`** (verified: no
   `pywebview` line, but `pyproject.toml:31` lists it as a runtime
   dependency). A user who runs `pip install -r requirements.txt` and
   then `iraqi-translate ui` gets an `ImportError`. This is a
   packaging bug, not a code bug.

2. **Python version mismatch.** `pyproject.toml:10` declares
   `requires-python = ">=3.11,<3.12"` but `README.md:30` says "the test
   venv runs Python 3.10." Either the pin is wrong or the README is
   wrong — both cannot be true. The codebase uses `Literal` and
   `Self`-style typing features that work on 3.10, but `match` statements
   (if any) require 3.10+. The pin must be reconciled with reality.

3. **`ARCHITECTURE.md` and `PROMPTS.md` are referenced in
   `pyproject.toml` comments but do not exist** (verified). The
   references are stale — the component refactor moved architecture
   docs to `AGENTS.md` and prompt docs to `prompts.py`. The
   `pyproject.toml` comments must point to the files that actually
   exist.

4. **`gradio` is a runtime dep in `requirements.txt:22` but optional in
   `pyproject.toml:42-44`** (verified). A user who installs from
   `requirements.txt` gets `gradio` (~50 MB); a user who installs from
   `pyproject.toml` does not. The two install paths produce different
   environments.

5. **Three completed OpenSpec changes are unarchived:**
   - `refactor-to-component-architecture` — 80/80 tasks done
   - `solid-clean-code-refactor` — 34/34 tasks done
   - `fix-mypy-strict-errors` — marked complete

   `openspec list` shows all three as "✓ Complete" but they still live
   in `openspec/changes/` instead of `openspec/changes/archive/`. Their
   delta specs have not been merged into `openspec/specs/`, so the
   source-of-truth specs are stale and do not reflect the component
   architecture that actually exists in `src/components/`.

6. **`openspec/config.yaml:13` references `qwen2.5:7b-instruct-q5_K_M`
   but `config.yaml:11` uses `gemma3:4b`** (verified). `AGENTS.md` §3
   documents this discrepancy ("both fit the RAM ceiling") but the
   `openspec/config.yaml` context block is stale and should match the
   runtime source of truth.

These are not code bugs — they are documentation and packaging bugs
that erode trust in the build. A new contributor who follows
`requirements.txt` will get a broken UI; a contributor who reads the
specs will see a stale architecture.

## What Changes

1. **Fix `requirements.txt`:**
   - Add `pywebview>=5.0,<7` (matches `pyproject.toml`).
   - Move `gradio>=4.0,<5` to a comment-annotated "optional" section
     with a note that it is not required for the CLI or desktop UI.
   - Add `defusedxml>=0.7,<1` (added by
     `harden-untrusted-input-surfaces`; listed here for completeness —
     that change owns the actual addition).
   - Sort dependencies alphabetically within each section.

2. **Reconcile `pyproject.toml` with `requirements.txt`:**
   - Move `gradio` from `[project.optional-dependencies]` to a
     `[project.optional-dependencies.ui-extra]` group (or keep it
     optional but document that `requirements.txt` includes it for
     convenience).
   - Update the `requires-python` pin: read `README.md` and the actual
     test venv version; if the test venv is 3.10, relax the pin to
     `>=3.10,<3.12` and verify the codebase does not use 3.11-only
     features (`Self`, `ExceptionGroup`, `tomllib`). If it does use
     3.11-only features, update `README.md` to say 3.11 is required.
   - Replace `ARCHITECTURE.md` references in `pyproject.toml` comments
     with `AGENTS.md`.
   - Replace `PROMPTS.md` references in `pyproject.toml` comments with
     `src/components/translation_pipeline/prompts.py`.

3. **Archive the three completed OpenSpec changes:**
   - `openspec archive refactor-to-component-architecture`
   - `openspec archive solid-clean-code-refactor`
   - `openspec archive fix-mypy-strict-errors`
   - After each archive, run `openspec validate --all` to confirm the
     merged specs are valid.

4. **Update `openspec/config.yaml`:**
   - Change the model name in the `context` block from
     `qwen2.5:7b-instruct-q5_K_M` to `gemma3:4b` to match
     `config.yaml` (the runtime source of truth). Add a note that
     `qwen2.5:7b-instruct-q5_K_M` is an alternative that also fits the
     RAM ceiling.

5. **Update `README.md`:**
   - Fix the Python version statement to match the reconciled pin.
   - Add a "Dependencies" subsection noting that `requirements.txt` is
     the canonical install list and `pyproject.toml` is for editable
     installs (`pip install -e .`).
   - Document the optional `gradio` dependency.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: `ExcelConfig` is not touched here (that is
  `harden-untrusted-input-surfaces`); this change only touches
  `pyproject.toml`, `requirements.txt`, `openspec/config.yaml`, and
  `README.md`. No spec-level behavior changes — this is a
  build/documentation hygiene change. However, archiving the three
  completed changes WILL merge their delta specs into the
  source-of-truth specs, so the `config`, `infrastructure`,
  `interfaces`, `knowledge_sources`, and `translation_pipeline` specs
  will be updated by the archive operation itself (not by hand-written
  deltas in this change).

## Impact

**Affected files:**
- `requirements.txt` (add `pywebview`, move `gradio` to optional,
  sort)
- `pyproject.toml` (reconcile `requires-python`, fix
  `ARCHITECTURE.md`/`PROMPTS.md` references, reconcile `gradio`)
- `openspec/config.yaml` (model name)
- `README.md` (Python version, dependencies subsection)
- `openspec/changes/` → `openspec/changes/archive/` (three changes
  moved by `openspec archive`)
- `openspec/specs/*/spec.md` (merged from the three archived changes
  by the archive operation)

**APIs:** None.

**Specs:** The three archive operations merge deltas into the
source-of-truth specs. This change does not hand-write any delta specs
— the archive operation is the mechanism. After archiving,
`openspec validate --all` must pass.

**Migration path:**
- Users must re-run `pip install -r requirements.txt` to pick up
  `pywebview` (and `defusedxml` from
  `harden-untrusted-input-surfaces`).
- No data migration; no DB schema changes.

**Rollback plan:**
- `git revert` for the file edits. The three archive operations can be
  reversed by `git revert` as well (the archive is a filesystem move +
  spec merge, both tracked by git).

**Build impact:**
- Closes audit findings TD-1 (Critical: `pywebview` missing), TD-2
  (Critical: Python version mismatch), TD-3/4 (Critical:
  `ARCHITECTURE.md`/`PROMPTS.md` missing), TD-5 (High: `gradio` drift),
  TD-6/7/8 (High: unarchived changes), TD-10 (Medium: openspec model
  name).
