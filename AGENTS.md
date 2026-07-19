# AGENTS.md — Iraqi Legal Translation Agent

> **Authoritative development guide for all AI agents and human contributors
> working on this repository.** Read this document and the relevant
> `openspec/specs/<capability>/spec.md` *before* writing any code.

This project is a **local, offline-first Agentic RAG system** for translating
Iraqi legal texts (Arabic ⇄ English). It enforces strict terminology adherence
via a deterministic glossary, retrieves context from a ChromaDB corpus of Iraqi
laws, and orchestrates a **Translator → Auditor → Revise** loop through
LangGraph with bounded retries and dual-agent quality assurance.

The system is engineered for an **8 GB RAM** hard ceiling, **no telemetry**,
**single-user, single-session** operation, and **no cloud calls by default**.
The default LLM backend is Ollama (local, offline); an **opt-in** Google Gemini
API cloud backend (`llm_backend: gemini`) is the only sanctioned cloud path.
See `README.md` [§2 Quick Start (How to Run)](README.md#2-quick-start-how-to-run)
for the fast path from a clean clone to a working translation.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Technology Stack](#3-technology-stack)
4. [Directory Structure](#4-directory-structure)
5. [Development Principles](#5-development-principles)
6. [OpenSpec Workflow](#6-openspec-workflow)
7. [AI Agent Rules](#7-ai-agent-rules)
8. [Coding Standards](#8-coding-standards)
9. [Testing Standards](#9-testing-standards)
10. [Verification Checklist](#10-verification-checklist)
11. [Pull Request Guidelines](#11-pull-request-guidelines)
12. [Security Guidelines](#12-security-guidelines)
13. [Documentation Guidelines](#13-documentation-guidelines)
14. [Definition of Done](#14-definition-of-done)

---

## 1. Project Overview

The **Iraqi Legal Translation Agent** translates Iraqi statutory and
jurisprudential text between Arabic and English. It combines:

- A **deterministic Exact-Match Glossary** (SQLite + JSON) that overrides LLM
  output before and after generation, guaranteeing term consistency even when
  the model drifts.
- A **ChromaDB** vector store of Iraqi laws (Civil Code, Penal Code, Civil
  Procedure Code, Commercial Code, …) for Retrieval-Augmented Generation.
- Two specialized LLM agents — a **Translator** (produces a draft) and an
  **Auditor** (approves or returns the draft with a structured critique) —
  orchestrated by **LangGraph**.
- **Translation Memory (TM)** for instant reuse of previously translated
  sentences.
- **Human-in-the-loop (HITL)** review with correction persistence.
- Optional **web search** over Iraqi legal sources (Ministry of Justice,
  National Library, Dijlex, UR Portal).

All inference is served by a local **Ollama** daemon (default) running a
quantized model that fits the 8 GB RAM envelope. An opt-in Google Gemini API
cloud backend (`llm_backend: gemini`) is the only sanctioned cloud path; when
it is disabled (the default), no component transmits data off the host.

### Non-Goals

- No cloud LLM calls except the opt-in Google Gemini API backend
  (`llm_backend: gemini`). No OpenAI, Anthropic, or any other remote inference.
- No multi-tenant serving. Single-user, single-session.
- No fine-tuning pipeline in this repository — glossary + RAG is the alignment
  strategy.
- No translation of non-Iraqi legal systems unless explicitly added to the
  corpus.

---

## 2. Architecture Overview

The system follows a **component-based architecture** with four bounded-context
components plus a `config` package. Each component owns a `models.py` and
depends on **protocols (PEP 544)**, not concretions. The composition root is
`src/app.py`, which wires all dependencies.

| Component | Responsibility |
|---|---|
| `infrastructure` | LLM engine adapter, embeddings, RAM guard, run logging |
| `knowledge_sources` | Glossary, ChromaDB retrieval, Translation Memory, legal search, ingestion |
| `translation_pipeline` | LangGraph state machine, translator/auditor nodes, prompts, parsers, decision, exceptions |
| `interfaces` | CLI, pywebview UI, Tkinter UI, HITL review, MCP server, orchestration seam |

### Component Dependency Graph

(Verified against actual imports in `src/components/interfaces/orchestration.py`
and `src/components/translation_pipeline/graph.py`.)

```
src/app.py  ──▶  interfaces  (Typer app entry point)

interfaces               ──▶  translation_pipeline   (build_graph, TranslationState)
interfaces               ──▶  infrastructure         (LLMEngineAdapter, EmbeddingAdapter, RunLogger)
interfaces               ──▶  knowledge_sources      (GlossaryIndex, TranslationMemory)
interfaces               ──▶  config                 (AppConfig)

translation_pipeline     ──▶  infrastructure         (LLMEngineAdapter, EmbeddingAdapter, RunLogger)
translation_pipeline     ──▶  knowledge_sources      (GlossaryIndex, TranslationMemory)
translation_pipeline     ──▶  config                 (AppConfig)

config                   ◀──  all components          (AppConfig is read by all; depends on nothing in src/)

No component depends on interfaces. The graph is strictly acyclic.
```

> **Note:** `interfaces` has **direct** dependencies on `infrastructure` and
> `knowledge_sources` (not only via `translation_pipeline`) — it wires adapters
> and stores itself at the composition root. Do not assume a layered
> `interfaces → translation_pipeline → infrastructure` chain.

### LangGraph Topology

```
preprocess → web_search → tm_lookup → [ tm_bypass | translate → auditor → (approve | revise) ] → finalize → END
```

- A TM hit with similarity `>= tm_similarity_threshold` bypasses the LLM
  entirely (`tm_bypass → finalize`).
- The Auditor returns `APPROVE` (→ finalize) or `REVISE` (→ translate, up to
  `max_revisions`, then finalize with a warning).
- Routing functions (`route_after_tm`, `route_audit`) are **pure** — they must
  not mutate state.

### Dependency Injection

`build_graph` binds engines to node functions with `functools.partial` so each
node closure has the LangGraph-required `(state) -> state` signature while still
receiving its engines via **keyword-only args** (DIP). No concrete engine is
imported inside the pipeline — only protocols.

---

## 3. Technology Stack

The full technology stack and 8 GB RAM budget are documented in `README.md` §2–3
(canonical source). This section lists only the constraints an agent must
verify before writing code — it intentionally does not duplicate the stack
table to avoid drift (DRY).

### Agent-Critical Constraints (Verify before coding)

- Never load a model > 8B params; runtime default is `gemma3:4b` (`config.yaml`).
- ChromaDB: **PersistentClient only** (never client/server mode).
- Concurrency: 1 in-flight request max; embedding batch ≤ 32; context ≤ 8192 tokens.
- **No telemetry, no third-party network calls.** The default LLM backend is
  Ollama (local, offline). An **opt-in** Google Gemini API cloud backend
  (`llm_backend: gemini`) is the only sanctioned cloud path; it requires the
  `GEMINI_API_KEY` environment variable, lazily imports `google-genai`, and
  enforces a process-local RPM cap. All other cloud LLM providers are
  out-of-scope.
- Single-user, single-session.
- **Note:** `openspec/config.yaml` references `qwen2.5:7b-instruct-q5_K_M`, but
  `config.yaml` is the runtime source of truth (`gemma3:4b`). Both fit the RAM
  ceiling.

---

## 4. Directory Structure

```
translater/
├── AGENTS.md                     # This document (canonical AI agent guide)
├── README.md                     # User-facing documentation
├── pyproject.toml                # Packaging, ruff, mypy, pytest config
├── pytest.ini                    # Test markers + addopts
├── config.yaml                   # Runtime configuration (source of truth)
├── requirements.txt
├── run.bat                       # Windows launcher (interactive menu)
├── data/
│   ├── glossary/                 # JSON glossary sources (version-controlled)
│   ├── corpus/                   # Iraqi legal text (AR + EN)
│   └── raw/                      # Raw uploads (gitignored)
├── db/                           # Generated databases (gitignored)
│   ├── glossary.sqlite
│   ├── tm.sqlite
│   └── chroma/
├── logs/                         # Run logs (run_<id>.jsonl)
├── openspec/                     # Spec-driven development (source of truth)
│   ├── config.yaml
│   ├── specs/                    # Current system behavior specs
│   └── changes/                  # Change proposals (in-progress & archived)
├── src/
│   ├── app.py                    # DI entry point + console script
│   ├── config/                   # Configuration package
│   │   ├── config.py             # load_config, AppConfig, ConfigError
│   │   ├── cli.py                # Typer CLI for config utilities
│   │   └── models.py             # PathsConfig, ChromaConfig (Pydantic)
│   └── components/               # 4 bounded-context components
│       ├── infrastructure/       # llm, embeddings, memory, run_logging, models
│       ├── knowledge_sources/    # glossary, retrieval, tm, legal_search, ingestion, models
│       ├── translation_pipeline/ # graph, nodes, prompts, decision, exceptions, protocols, models
│       └── interfaces/           # cli, web_ui, tk_ui, hitl, mcp_server, orchestration, models
└── tests/                        # Test suite (markers: unit/adapter/integration/e2e/eval/slow)
```

---

## 5. Development Principles

The project follows an **AI-Native, spec-driven** process based on OpenSpec.
The mandatory workflow is:

```
Research → Plan → Tasks → Build → Verify
```

### Foundational Principles

- **SOLID** — each component has one responsibility; dependencies point at
  protocols (PEP 544), not concretions; extensions are additive (OCP).
- **DRY** — closed string sets and magic numbers live as named constants.
- **KISS** — keep functions small and readable; prefer composition over inheritance.
- **YAGNI** — do not build capabilities the specs do not require.
- **DIP** — Dependency Injection via **keyword-only args**; the composition root
  (`src/app.py`, `build_graph`) is the only place concrete engines are wired.

### Conventions (must follow)

- **Conventional commits:** `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
- **State:** TypedDicts (PEP 692) for LangGraph state — *not* Pydantic — for
  LangGraph compatibility.
- **Config:** Pydantic models for configuration *only* (`AppConfig`,
  `PathsConfig`, `ChromaConfig`).
- **Adapter seams:** Protocols `LLMEngineAdapter`, `EmbeddingAdapter`,
  `HumanReviewer`, `GlossaryScanner`, `ContextRetriever`, `WebSearcher`.
- **Prompts:** Versioned constants (V1–V4); V4 is the current default. Prompt
  text is *versioned code* — do not rewrap or reformat it.
- **Exceptions:** Hierarchy rooted at `LegalTranslationError`. Adapters catch
  engine-specific errors and re-raise domain exceptions; nodes and the CLI only
  ever see domain exceptions.
- **Style:** `ruff` line-length = 100; `mypy strict = true`; target `py311`.
- **Bilingual scenarios:** Specs include Arabic + English scenarios where the
  behavior is language-dependent.

---

## 6. OpenSpec Workflow

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for
spec-driven development. **Specs are the contract.** Every requirement in a spec
MUST be preserved unless a change proposal explicitly marks it as
`MODIFIED` or `REMOVED`.

### Where the specs live

```
openspec/
├── config.yaml                          # Project context, tech stack, constraints, per-artifact rules
├── specs/                               # Source-of-truth specs (current system behavior)
│   ├── config/spec.md                   # Configuration loading & validation (5 requirements)
│   ├── translation_pipeline/spec.md     # LangGraph state machine, nodes, prompts, exceptions (9 requirements)
│   ├── knowledge_sources/spec.md        # Glossary, retrieval, TM, legal search, ingestion (6 requirements)
│   ├── infrastructure/spec.md           # LLM adapter, embeddings, memory/RAM guard, run logging (4 requirements)
│   └── interfaces/spec.md               # CLI, web UI, Tkinter UI, MCP server, HITL (7 requirements)
└── changes/                             # Change proposals (in-progress & archived)
    └── refactor-to-component-architecture/
        ├── proposal.md                  # WHY the change, scope, migration path, rollback plan
        ├── design.md                    # Target architecture, dependency diagram, decisions
        ├── tasks.md                     # Ordered task list (101 tasks)
        └── specs/                       # Delta specs (ADDED/MODIFIED/REMOVED requirements)
```

### OpenSpec Rules for AI Agents

1. **Read before you write.** Before implementing any feature, bugfix, or
   refactor, read the relevant spec(s) in `openspec/specs/<capability>/spec.md`.
   The specs are the authoritative description of expected behavior — each
   requirement has Given/When/Then scenarios.
2. **Check for active changes.** Run `openspec list` to see in-progress change
   proposals. If a change exists that affects your task, read its `proposal.md`,
   `design.md`, and `tasks.md` first. Follow the task list in `tasks.md` when
   executing the change.
3. **Specs are the contract.** Every requirement in a spec MUST be preserved
   unless a change proposal explicitly marks it as MODIFIED or REMOVED. Do not
   silently change behavior that a spec documents.
4. **New work needs a change proposal.** For any non-trivial change (new
   feature, refactor, behavior modification), create an OpenSpec change first:
   ```
   openspec new change <change-name> --goal "<one-sentence goal>"
   ```
   Then write `proposal.md` → `specs/` (delta) → `design.md` → `tasks.md` in
   that order. Validate with `openspec validate <change-name>` before
   implementing.
5. **Validate after changes.** After implementing, run `openspec validate --all`.
   All specs and changes must pass. If a change is complete, archive it:
   ```
   openspec archive <change-name>
   ```
6. **Use the project context.** `openspec/config.yaml` contains the tech stack,
   hard constraints (8 GB RAM, no cloud calls, single-user), conventions (DI via
   keyword-only args, TypedDicts for state, Pydantic for config, versioned
   prompts), and per-artifact rules. Follow these.

### Current active changes

| Change | Status |
|---|---|
| `refactor-to-component-architecture` | **Archived** (`openspec/changes/archive/2026-07-18-refactor-to-component-architecture/`). Component directories exist in `src/components/`; delta specs folded into the source-of-truth specs. |
| `fix-mypy-strict-errors` | **Archived** (`openspec/changes/archive/2026-07-18-fix-mypy-strict-errors/`). |
| `solid-clean-code-refactor` | **Archived** (`openspec/changes/archive/2026-07-18-solid-clean-code-refactor/`). |
| `add-gemini-api-backend` | **Archived** (`openspec/changes/archive/2026-07-19-add-gemini-api-backend/`). |
| `fix-build-and-spec-hygiene` | In progress (`openspec/changes/fix-build-and-spec-hygiene/`). |

> The `openspec/` directory is **gitignored** (local spec-driven development,
> not part of the tracked codebase — see `.gitignore`). It exists only on
> contributors' machines after they run `openspec init` / `openspec new change`.
> The archived change folders above are therefore local-only; the table
> reflects the local state, not anything checked into git.

### Phase 1 — Research

Before writing any code:

- Read the relevant `openspec/specs/<capability>/spec.md`.
- Run `openspec list` to see in-progress change proposals.
- Read source files in the affected components.
- Identify dependencies, risks, and unknowns.
- Search for related implementations inside the project.
- **Never assume behavior** — verify it by reading the code.

**Deliverable:** research summary, current architecture understanding, risks,
unknowns.

### Phase 2 — Plan

Create an implementation plan (no coding yet). Include:

- Problem statement
- Proposed solution
- Affected modules / files (old path → new path)
- API, database, UI changes
- Security and performance considerations
- Rollback strategy

For non-trivial changes, create an OpenSpec change proposal first:

```powershell
openspec new change <change-name> --goal "<one-sentence goal>"
```

Then write, in order: `proposal.md` → `specs/` (delta) → `design.md` → `tasks.md`.
Validate with `openspec validate <change-name>` before implementing.

### Phase 3 — Tasks

Break the implementation into **atomic** tasks. Each task must be:

- [ ] Small
- [ ] Independent
- [ ] Testable
- [ ] Reviewable

Never combine multiple major changes into one task. One file move per task;
include a verification step after each component migration.

### Phase 4 — Build

Implement tasks sequentially. Requirements:

- Follow the existing architecture and reuse existing components.
- Avoid duplicate code; keep functions small and readable.
- Add comments only when necessary (the codebase favors self-documenting code
  with docstrings on public APIs).
- Follow SOLID, DRY, KISS, YAGNI.
- Prefer modifying existing code over creating new files.

### Phase 5 — Verify

Before considering work complete:

- [ ] Run tests, lint, type-check, complexity.
- [ ] Verify no regressions; validate edge cases.
- [ ] `openspec validate --all` passes (0 failures).
- [ ] Specs reflect the current behavior after the change.
- [ ] Archive completed changes: `openspec archive <change-name>`.

**Produce a verification summary** with the actual command output.

### Useful OpenSpec Commands

| Command | Purpose |
|---|---|
| `openspec list --specs` | List all source-of-truth specs |
| `openspec list` | List all change proposals |
| `openspec validate --all` | Validate all specs and changes |
| `openspec validate <change-name>` | Validate a single change |
| `openspec status --change <name>` | Show artifact completion status |
| `openspec show <name>` | Display a change or spec |
| `openspec new change <name> --goal "..."` | Create a new change proposal |
| `openspec archive <name>` | Archive a completed change into specs |
| `openspec context` | Print working context and root |

---

## 7. AI Agent Rules

The AI agent **must always**:

1. **Research before planning** — read specs and source before designing.
2. **Plan before coding** — no implementation without a plan.
3. **Break work into tasks** — atomic, testable, reviewable.
4. **Build incrementally** — one task at a time, in dependency order.
5. **Verify everything before completion** — show evidence, never assert.
6. **Explain important architectural decisions** — record the *why*.
7. **Preserve project consistency** — follow existing patterns and conventions.
8. **Respect existing design patterns** — DI, protocols, TypedDicts, versioned prompts.
9. **Avoid unnecessary dependencies** — never add a library not already in use
   without justification; prefer stdlib.
10. **Produce maintainable, production-quality code.**

The AI agent **must never**:

- Guess APIs or invent project conventions.
- Duplicate logic or introduce dead code.
- Ignore failing tests or leave TODOs without explanation.
- Modify behavior that a spec documents without an OpenSpec change proposal.
- Violate the hard constraints (8 GB RAM, no cloud calls, PersistentClient only,
  single in-flight request).
- Add a dependency published less than 7 days ago, or use floating ranges
  (`latest`, `*`, unbounded `>=`).

---

## 8. Coding Standards

### Always

- Prefer modifying existing code over creating new files.
- Minimize complexity; keep functions small and single-purpose.
- Preserve backwards compatibility when possible.
- Use descriptive naming; avoid magic numbers (use named constants).
- Handle errors explicitly at the right boundary (adapters map engine errors to
  domain exceptions).
- Validate inputs.
- Use **keyword-only args** for dependency injection.
- Use TypedDicts for LangGraph state; Pydantic for config only.
- Use Protocols (PEP 544, `@runtime_checkable`) for adapter seams.
- Write docstrings on public APIs; comments only where logic is non-obvious.
- Follow `ruff` line-length 100 and `mypy strict`.
- Add `import logging; logger = logging.getLogger(__name__)` to every module
  that can raise or catch exceptions. Use `logger.warning` for expected
  failures, `logger.exception` at UI/process boundaries (the exception is
  already being surfaced to the caller — log the traceback for diagnostics).

### Never

- Guess APIs or invent conventions.
- Duplicate logic.
- Ignore failing tests.
- Leave TODOs without explanation.
- Introduce dead code.
- Reformat versioned prompt constants (they are code, not prose).
- Import concrete engines inside the pipeline — depend on protocols.
- Mutate state inside LangGraph conditional-edge routing functions.
- Use a bare `except Exception:` without a `logger.exception` (or
  `logger.warning`) call. UI boundaries are the only exception — they may
  use `except Exception as e: # noqa: BLE001 -- UI boundary: log + surface
  to user` followed by `logger.exception(...)`.

### Per-File Ignore Policy

`pyproject.toml` documents `ruff` per-file-ignores with inline justifications
(e.g. prompt constants, embedded HTML/CSS in `web_ui.py`, the mandated
6-arg `LLMEngineAdapter.generate` signature, DI seams with many kwargs). When
moving or adding files, update the `[tool.ruff.lint.per-file-ignores]` table
and keep the justification comment.

---

## 9. Testing Standards

### Test Markers (`pytest.ini`)

| Marker | Scope | Budget |
|---|---|---|
| `unit` | Pure logic | < 100ms each |
| `adapter` | Adapter isolation, error translation, engine swap, import boundary | < 500ms each |
| `integration` | Real SQLite/ChromaDB in a temp dir | < 1s each |
| `e2e` | Full pipeline with mocked LLM | < 5s each |
| `eval` | Auditor evaluation matrix | may be slow |
| `slow` | > 5s | excluded from default CI run |

Default run: `addopts = -m "not slow" --strict-markers --tb=short`.

### Standards

- Write tests **first** for features and bugfixes (test-driven development).
- Each requirement must be traceable to an existing test or a test to be added.
- Use deterministic fakes for LLM/embedder adapters in e2e tests; never hit the
  real Ollama daemon in the test suite.
- Include bilingual scenarios (Arabic input + English output, and vice versa)
  where the behavior is language-dependent.
- Integration tests must use temp directories, never the real `db/` artifacts.
- A test must fail for the right reason and pass for the right reason.

### Commands

```powershell
pytest --tb=short -q              # default (excludes slow)
pytest -m unit -q                 # only unit tests
pytest -m "not slow" --strict-markers
```

---

## 10. Verification Checklist

Run these before claiming any task is complete. **Evidence before assertions.**

```powershell
# Tests
pytest --tb=short -q

# Lint
ruff check src/ tests/

# Type-check
mypy src/

# Complexity
radon cc src/ -a

# Spec validation
openspec validate --all

# Smoke test (requires Ollama running)
python -m src.app doctor
python -m src.app translate --input "المادة ١" --direction ar-en
```

### Pre-Completion Checklist

- [ ] All relevant tests pass (`pytest --tb=short -q`).
- [ ] `ruff check src/ tests/` is clean.
- [ ] `mypy src/` is clean (strict).
- [ ] No regressions; edge cases validated.
- [ ] `openspec validate --all` passes (0 failures).
- [ ] Specs reflect current behavior; change proposal archived if complete.
- [ ] No new dependencies without justification.
- [ ] Documentation updated where behavior changed.
- [ ] Verification summary produced with actual command output.

---

## 11. Pull Request Guidelines

Follow the template in `.github/PULL_REQUEST_TEMPLATE.md`. Conventional commits
are required.

### CLI Exit Codes

| Code | Meaning |
|------|---------|
| 0    | Success |
| 1    | Generic / unhandled error |
| 2    | Ollama / embedding connection failure |
| 3    | RAM guard exceeded |
| 4    | Path containment violation |
| 5    | Input validation error (JSONL schema, etc.) |
| 6    | I/O error (OSError) |

The `handle_pipeline_errors` decorator in `src/utils/cli_errors.py` maps
domain exceptions to these codes. UI-boundary catches in `web_ui.py` and
`tk_ui.py` log via `logger.exception` and surface the error to the user
without crashing.

### UiBackend Protocol

The `UiBackend` protocol in `src/components/interfaces/ui_backend.py` defines
a callable interface for UI launchers: `__call__(cfg: AppConfig, adapters:
Adapters) -> None`. Both `web_ui.launch_ui` and `tk_ui.launch_ui` satisfy this
protocol. The `ui` CLI command selects the backend via `cfg.ui.backend`
(`"web"` or `"tk"`, default `"web"` in `config.yaml`).

### Commit Message Format

```
<type>: <imperative summary>

<optional body explaining why, not what>

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

Types: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.

### PR Checklist

- [ ] Summary describes *what* and *why*.
- [ ] Type of change marked (bug fix / feature / breaking / docs / test / refactor).
- [ ] Related issue linked (`Closes #<n>`).
- [ ] **OpenSpec:** specs reviewed; `openspec validate --all` passes; change
      proposal created/updated if behavior changes; delta specs use
      `ADDED`/`MODIFIED`/`REMOVED` markers with Given/When/Then scenarios.
- [ ] Changes listed item-by-item.
- [ ] All existing tests pass; lint and type-check clean on changed files.
- [ ] New tests added for new functionality.
- [ ] Manual testing described (if applicable).
- [ ] Self-review completed; comments added only for complex logic.
- [ ] Documentation updated (README, AGENTS.md, specs) if needed.
- [ ] No new dependencies without justification.
- [ ] **If the PR does not modify behavior**, explain why no OpenSpec change is
      needed.

### Branching

- CI runs on `main` and `develop` (`.github/workflows/ci.yml`): `ruff check
  src/ tests/` then `pytest tests/ -q` on Python 3.11.
- Do not push directly to `main` for non-trivial changes; open a PR.
- Never force-push or rewrite shared history without explicit confirmation.

---

## 12. Security Guidelines

- **No secrets or keys in the repository.** Never commit credentials, API keys,
  or connection strings.
- **No cloud calls by default.** The default LLM/embedding backend is Ollama
  (local, offline). The only sanctioned cloud path is the opt-in Google Gemini
  API backend (`llm_backend: gemini`), which requires `GEMINI_API_KEY` and
  lazily imports `google-genai`. No other remote LLM, embedding, or telemetry
  endpoints are permitted.
- **No third-party network calls** except the optional, opt-in Iraqi legal web
  search (`web_search_enabled: false` by default) and the opt-in Gemini backend.
- **Never log or expose secrets.** Run logs (`logs/run_<id>.jsonl`) must not
  contain credentials.
- **Never modify security policies or compliance controls** (e.g. branch
  protection, `.npmrc`/pip security settings) to work around CI failures —
  escalate to the user.
- Corpus data must come from **public official gazette publications**. With the
  default Ollama backend, no component transmits data off the host; with the
  opt-in Gemini backend, only the translation text is sent to Google's API
  (never the corpus or glossary wholesale).
- Validate all external input (corpus files, glossary JSON, CLI args, MCP
  requests); raise domain exceptions on invalid input.
- Adapters are the trust boundary: catch engine-specific errors and re-raise
  domain exceptions so nodes and the CLI never see engine types.

### 12.1 Input validation surfaces (harden-untrusted-input-surfaces)

The following validation surfaces are enforced by the `src/utils/` package
and the component-level guards:

- **Path containment** (`src/utils/paths.py`): All `--input` and `--out`
  paths in the CLI (`translate`, `batch`, `excel`) and the orchestration seam
  (`_resolve_input`) are validated against the project root. Violations raise
  `PathContainmentError` (exit code 4).
- **Zip-slip prevention** (`src/utils/zip_safe.py`): Every zip entry in an
  `.xlsx` workbook is validated before read/write — absolute paths, `..`
  segments, and backslash separators are rejected.
- **XXE defense** (`defusedxml`): `excel.py` uses
  `defusedxml.ElementTree.fromstring` instead of `xml.etree.ElementTree` to
  prevent entity expansion attacks.
- **XML injection prevention** (`src/utils/xml_escape.py`): LLM output
  inserted into OOXML text nodes is escaped via `escape_xml_text`.
- **Excel size caps**: `ExcelConfig.max_xlsx_bytes` (100 MiB) and
  `ExcelConfig.max_segments` (10000) reject oversized workbooks.
- **Atomic output**: Excel output is written to a `.tmp` file then
  `os.replace`d, so a crash never leaves a partial workbook.
- **JSONL schema validation** (`src/utils/jsonl_schema.py`): Batch records
  and parallel-pair files are validated via Pydantic models
  (`BatchRecord`, `ParallelPair`) with max-length constraints.
- **MCP input validation + rate limiting**: MCP tool queries are capped at
  500 chars; `max_results` is clamped to [1, 100]; a token-bucket rate
  limiter (10 req/min) prevents abuse.
- **pywebview session token**: The `Api` class generates a session token
  (`secrets.token_urlsafe(32)`) injected into the page at load time; every
  state-mutating `Api` method requires the token as its first argument.
- **Legal search URL allowlist** (`legal_search.py`): Only
  `moj.gov.iq`, `dijlex.com`, `urportal.ur.gov.iq`, and `nlb.gov.iq`
  (plus `www.` variants) are allowed. Redirects are manually validated
  (max 3 hops); JSON-LD scripts are capped at 1 MiB.

### 12.2 Resource management (fix-resource-lifetimes)

All resource-owning classes implement the context-manager protocol
(`__enter__`/`__exit__`/`close()`) as the standard for resource cleanup:

- **`TranslationMemory`** (`tm.py`): Uses `threading.RLock` to serialize
  all SQLite access (thread-safe). `close()` is idempotent and guarded
  by `weakref.finalize` as a safety net. Use `with TranslationMemory(...) as tm:`.
- **`RunLogger`** (`run_logging.py`): `log_node` catches `OSError` (disk
  full) and disables itself non-fatally — the pipeline continues. Use
  `with RunLogger(...) as logger:`.
- **`Embedder`** (`embeddings.py`): `close()` calls `client.close()` if
  available; idempotent. The module-level `_default_embedder` global has
  been removed — callers must inject an `Embedder` explicitly (DIP). Use
  `with Embedder(...) as embedder:`.
- **`OllamaEngineAdapter`** (`llm.py`): Same pattern as `Embedder`.
  Use `with OllamaEngineAdapter(...) as llm:`.
- **`ChromaStore`** (`retrieval.py`): `__exit__` calls `_close_handles()`.
  `_write_collection` wraps its body in `try/except` that releases handles
  on failure (Windows file-lock safety). Use `with ChromaStore(...) as store:`.
- **CLI callers**: `translate`, `batch`, `excel` commands wrap `RunLogger`
  in `with`. `tm_build`, `tm_build_parallel`, `tm_add_parallel` wrap
  `TranslationMemory` in `with`.
- **Web UI**: `launch_ui` calls `_close_adapters(adapters)` after
  `webview.start()` returns (window closed), releasing LLM, embedder, and TM.

---

## 13. Documentation Guidelines

- **Specs are the source of truth.** `openspec/specs/<capability>/spec.md`
  documents expected behavior with Given/When/Then scenarios.
- **Keep docs in sync with code.** When behavior changes, update the relevant
  spec (via a change proposal) and user-facing docs (`README.md`, `AGENTS.md`).
- **Do not create documentation files to describe changes or plans** unless
  explicitly requested. Persistent project info files (`AGENTS.md`, `README.md`)
  are the exception.
- **Docstrings** on public APIs; comments only where logic is non-obvious.
- **Versioned prompts** (`prompts.py`) are code — do not reformat them; they
  mirror `PROMPTS.md` verbatim.
- **Bilingual content:** include Arabic + English examples where the behavior
  is language-dependent.
- When discovering useful project info (build commands, conventions,
  verification steps), append to `AGENTS.md` rather than creating new docs.

---

## 14. Definition of Done

A task is complete only when **all** of the following are true and backed by
evidence:

- [ ] **Specs:** relevant `openspec/specs/<capability>/spec.md` read; behavior
      change covered by a validated OpenSpec change proposal; change archived
      if complete.
- [ ] **Code:** follows architecture, conventions, and coding standards; reuses
      existing components; no dead code or unexplained TODOs.
- [ ] **Tests:** new behavior covered by tests; all tests pass
      (`pytest --tb=short -q`); tests fail/pass for the right reasons.
- [ ] **Lint:** `ruff check src/ tests/` clean.
- [ ] **Types:** `mypy src/` clean (strict).
- [ ] **Complexity:** `radon cc src/ -a` acceptable (no new hotspots).
- [ ] **Specs valid:** `openspec validate --all` passes (0 failures).
- [ ] **No regressions:** edge cases validated; existing behavior preserved.
- [ ] **Constraints respected:** 8 GB RAM, no cloud calls by default (opt-in
      Gemini is the only sanctioned cloud path), PersistentClient
      only, single in-flight request, no new unmaintained dependencies.
- [ ] **Docs updated:** README / AGENTS.md / specs reflect the new behavior.
- [ ] **Verification summary** produced with actual command output.

---

*This guide is the authoritative reference for AI-assisted development on this
repository. It follows the [AGENTS.md open format](https://agents.md/) adopted
by OpenAI Codex, Cursor, Devin, Gemini CLI, and the broader AI coding agent
ecosystem. When it conflicts with a generic convention, this guide and the
OpenSpec specs win.*
