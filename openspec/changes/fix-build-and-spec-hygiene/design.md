## Context

The project's build configuration and OpenSpec state have drifted from
the codebase. `pywebview` is missing from `requirements.txt`; the
Python version pin contradicts the README; `ARCHITECTURE.md` and
`PROMPTS.md` are referenced but do not exist; `gradio` is a runtime dep
in one file and optional in another; and three completed OpenSpec
changes are unarchived, leaving the source-of-truth specs stale.

## Goals / Non-Goals

**Goals:**
- Make `pip install -r requirements.txt` produce a working environment
  for both the CLI and the desktop UI.
- Make `pyproject.toml` and `requirements.txt` agree on what is
  runtime vs. optional.
- Reconcile the Python version pin with reality (the actual test venv
  version and the language features the code uses).
- Replace stale file references in `pyproject.toml` comments with the
  files that actually exist.
- Archive the three completed OpenSpec changes so the source-of-truth
  specs reflect the component architecture that exists in
  `src/components/`.
- Update `openspec/config.yaml` to match `config.yaml`'s model name.

**Non-Goals:**
- Choosing a different LLM model — `gemma3:4b` is the runtime source of
  truth; this change only makes `openspec/config.yaml` agree with it.
- Adding new dependencies beyond `pywebview` and `defusedxml` (the
  latter is owned by `harden-untrusted-input-surfaces`).
- Rewriting `README.md` from scratch — only the Python version and
  dependencies subsection are touched.
- Hand-writing delta specs for the three archived changes — the
  `openspec archive` operation merges their existing deltas into the
  source-of-truth specs.

## Decisions

### D1: `requirements.txt` is the canonical install list

**Decision:** `requirements.txt` is the canonical list for
`pip install -r requirements.txt` (the documented install path in
README). `pyproject.toml` `[project.dependencies]` mirrors it for
`pip install -e .`. Optional dependencies (`gradio`) go in
`pyproject.toml [project.optional-dependencies]` AND in a
comment-annotated optional section at the bottom of
`requirements.txt`.

**Rationale:** Two install paths (`requirements.txt` and
`pip install -e .`) must produce the same environment for the runtime
deps. Optional deps are a convenience in `requirements.txt` (commented
out) and a proper extras group in `pyproject.toml`.

### D2: Reconcile Python pin by reading the code, not by guessing

**Decision:** Before changing `requires-python`, grep the codebase for
3.11-only features (`Self`, `ExceptionGroup`, `tomllib`, `match` on
custom classes). If none are found, relax the pin to `>=3.10,<3.12`
and update README to say "3.10 or 3.11." If any are found, update
README to say "3.11 required" and keep the pin.

**Rationale:** The pin must reflect what the code actually requires.
Guessing is how we got here.

### D3: Archive via `openspec archive`, not by hand

**Decision:** Use `openspec archive <change-name>` for each of the
three completed changes. This is the supported mechanism; it moves the
change to `archive/` and merges its delta specs into
`openspec/specs/`.

**Rationale:** Hand-merging deltas is error-prone and bypasses the
validator. The CLI exists for this.

### D4: `openspec/config.yaml` model name follows `config.yaml`

**Decision:** Change `openspec/config.yaml`'s context-block model name
from `qwen2.5:7b-instruct-q5_K_M` to `gemma3:4b`, with a note that
`qwen2.5:7b-instruct-q5_K_M` is an alternative.

**Rationale:** `config.yaml` is the runtime source of truth
(`AGENTS.md` §3). `openspec/config.yaml` is documentation; it must
agree with the runtime.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Archiving a change whose deltas conflict with the current source-of-truth specs | Run `openspec validate <change>` before archiving; the validator catches conflicts. |
| Relaxing the Python pin to 3.10 lets a user run on 3.10 and hit a 3.11-only feature we missed | The grep step (D2) is the mitigation; if any 3.11-only feature is found, keep the pin at 3.11. |
| Moving `gradio` to optional in `requirements.txt` breaks a user who relied on it being installed by default | Document in README that `gradio` is optional and how to install it. |
| `openspec archive` modifies many spec files in one operation | Run it one change at a time with `openspec validate --all` after each, so a conflict is attributable to a single archive. |

## Target directory tree (modified files only)

```
requirements.txt              # MODIFIED: + pywebview, gradio → optional section, sort
pyproject.toml                # MODIFIED: requires-python, ARCHITECTURE.md → AGENTS.md, PROMPTS.md → prompts.py, gradio optional
openspec/config.yaml          # MODIFIED: model name qwen2.5 → gemma3:4b
README.md                     # MODIFIED: Python version, dependencies subsection
openspec/
  changes/
    archive/                  # three changes moved here by `openspec archive`
      refactor-to-component-architecture/
      solid-clean-code-refactor/
      fix-mypy-strict-errors/
  specs/                      # merged from the three archived changes by the archive operation
    config/spec.md
    infrastructure/spec.md
    interfaces/spec.md
    knowledge_sources/spec.md
    translation_pipeline/spec.md
```
