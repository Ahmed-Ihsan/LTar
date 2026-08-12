# AGENTS.md — Iraqi Legal Translation Agent

A local, offline-first Agentic RAG system for translating Iraqi legal texts
(Arabic ⇄ English): deterministic glossary + ChromaDB corpus + a
Translator → Auditor → Revise loop orchestrated by LangGraph. Read this
document and the relevant `openspec/specs/<capability>/spec.md` *before*
writing any code.

Engineered for an **8 GB RAM** ceiling, **no telemetry**, **single-user,
single-session**, and **no cloud calls by default** (Ollama local; opt-in
Google Gemini is the only sanctioned cloud path). See `README.md`
[§2 Quick Start](README.md#2-quick-start-how-to-run) for the fast path.

---

## Setup & Commands

```powershell
# Environment (Python 3.11)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run the app (requires Ollama daemon running locally)
python -m src.app doctor                              # environment checks
python -m src.app translate --input "المادة ١" --direction ar-en
python -m src.app ui                                  # launch desktop UI
run.bat                                               # Windows launcher (14 options)

# Tests
pytest --tb=short -q                                  # default (excludes slow)
pytest -m unit -q                                     # only unit tests
pytest -m "not slow" --strict-markers
pytest tests/test_nodes.py -q                         # single file

# Lint / type-check / complexity
ruff check src/ tests/
mypy src/
radon cc src/ -a

# Spec-driven development (openspec/ is gitignored, local-only)
openspec list --specs                                 # list source-of-truth specs
openspec list                                         # list change proposals
openspec validate --all                               # validate all specs + changes
openspec new change <name> --goal "<one-sentence goal>"
openspec archive <name>                               # archive a completed change
```

CI (`.github/workflows/ci.yml`): `ruff check src/ tests/` then
`pytest tests/ -q` on Python 3.11, on `main` and `develop`.

---

## Hard Constraints (Verify before coding)

- **RAM:** Never load a model > 8B params; runtime default is `gemma3:4b`
  (`config.yaml`).
- **ChromaDB:** PersistentClient only (never client/server). Telemetry disabled.
- **Concurrency:** 1 in-flight request max; embedding batch ≤ 32;
  context ≤ 8192 tokens.
- **No telemetry, no third-party network calls.** Default backend is Ollama
  (local, offline). The only sanctioned cloud path is the opt-in Google Gemini
  API (`llm_backend: gemini`), which requires `GEMINI_API_KEY`, lazily imports
  `google-genai`, and enforces a process-local RPM cap (default 15). All other
  cloud LLM providers are out-of-scope.
- **Single-user, single-session.** No multi-tenant serving.
- **No fine-tuning pipeline** — glossary + RAG is the alignment strategy.
- **No translation of non-Iraqi legal systems** unless added to the corpus.
- **`config.yaml` is the runtime source of truth.** Note: `config.yaml` sets
  `top_k: 3`, but the `AppConfig` Pydantic default in `src/config/config.py` is
  `top_k: 8` — the `config.yaml` value wins at runtime; align the code default
  if editing it.

---

## Architecture Overview

Component-based, four bounded-context components plus `config` and `utils`.
Each component owns a `models.py` and depends on **protocols (PEP 544)**, not
concretions. Composition root: `src/app.py` wires all dependencies.

| Component | Responsibility |
|---|---|
| `infrastructure` | LLM adapter (Ollama + Gemini), embeddings, RAM guard, run logging |
| `knowledge_sources` | Glossary, ChromaDB retrieval, Translation Memory, legal search, ingestion |
| `translation_pipeline` | LangGraph state machine, translator/auditor nodes, prompts, parsers, decision, exceptions |
| `interfaces` | CLI, pywebview UI, Tkinter UI, HITL review, MCP server, document translation, orchestration seam |
| `config` | Configuration loading & validation (Pydantic models) |
| `utils` | Shared utilities: path validation, zip-slip prevention, XML escape, JSONL schemas, rate limiting, logging, batch size |

**Dependency graph** (strictly acyclic): `app.py → interfaces → {translation_pipeline, infrastructure, knowledge_sources, config, utils}`;
`translation_pipeline → {infrastructure, knowledge_sources, config}`. `interfaces`
has **direct** deps on `infrastructure` and `knowledge_sources` (it wires adapters
at the composition root) — do not assume a layered chain. `config`/`utils` are
read by all; nothing depends on `interfaces`.

**LangGraph topology:**
`preprocess → web_search → tm_lookup → [ tm_bypass | translate → auditor → (approve | revise) ] → finalize → END`
- TM hit `>= tm_similarity_threshold` bypasses the LLM (`tm_bypass → finalize`).
- Auditor: `APPROVE` (→ finalize) or `REVISE` (→ translate, up to
  `max_revisions`, then finalize with a warning).
- Routing functions (`route_after_tm`, `route_audit`) are **pure** — never
  mutate state. `finalize` includes a programmatic script guard.

**DI:** `build_graph` binds engines via `functools.partial` (keyword-only args).
No concrete engine is imported inside the pipeline — only protocols. Concrete
adapters are constructed only in `cli._construct_adapters()`.

**Exceptions:** All root at `LegalTranslationError`. Adapters catch
engine-specific errors and re-raise domain exceptions; nodes/CLI only see
domain exceptions. Branches: `AdapterError`, `GlossaryError`, `CorpusError`,
`RetrievalError`, `LLMRuntimeError` (Ollama/Gemini/LlamaCpp connection +
timeout subclasses), `EmbeddingError`, `AuditParseError`, `RAMGuardError`,
`InputValidationError` (`PathContainmentError`, `LegalSearchBlockedError`).

**Layout:** `src/components/<component>/` (4 components), `src/config/`,
`src/utils/`, `src/app.py`. Tests in `tests/` (markers:
unit/adapter/integration/e2e/eval/slow). `data/` (glossary, corpus, raw),
`db/` (gitignored), `logs/`, `openspec/` (gitignored). See `README.md` for the
full file tree.

---

## Code Style

- **Style:** `ruff` line-length = 100; `mypy strict = true`; target `py311`.
- **State:** TypedDicts (PEP 692) for LangGraph state — *not* Pydantic — for
  LangGraph compatibility.
- **Config:** Pydantic models for configuration *only* (`AppConfig`,
  `PathsConfig`, `ChromaConfig`, `ExcelConfig`, `WordConfig`, `PdfConfig`,
  `UiConfig`).
- **DI:** Keyword-only args for dependency injection. Composition root
  (`src/app.py`, `build_graph`, `cli._construct_adapters`) is the only place
  concrete engines are wired.
- **Adapter seams:** Protocols `LLMEngineAdapter`, `EmbeddingAdapter`,
  `HumanReviewer`, `GlossaryScanner`, `ContextRetriever`, `WebSearcher`,
  `UiBackend` (`@runtime_checkable`).
- **Models:** Frozen dataclasses with `slots=True` for component-internal
  models; `__slots__` for memory efficiency in adapter classes.
- **Prompts:** Versioned constants (V1–V4; V4 default). Prompt text is
  *versioned code* — do not rewrap or reformat it; it mirrors `PROMPTS.md`
  verbatim.
- **Logging:** `import logging; logger = logging.getLogger(__name__)` in every
  module that can raise/catch. `logger.warning` for expected failures,
  `logger.exception` at UI/process boundaries.
- **Resource management:** All resource-owning classes implement the
  context-manager protocol (`__enter__`/`__exit__`/`close()`); `close()` must
  be idempotent. Use `with` for `TranslationMemory`, `RunLogger`, `Embedder`,
  `OllamaEngineAdapter`, `GeminiEngineAdapter`, `ChromaStore`.
- **Per-file ignore policy:** `pyproject.toml` documents `ruff`
  per-file-ignores with inline justifications. Update the
  `[tool.ruff.lint.per-file-ignores]` table when moving/adding files.
- **Bilingual scenarios:** Specs include Arabic + English scenarios where
  behavior is language-dependent.

---

## Testing

- **Write tests first** for features and bugfixes (TDD).
- Each requirement must be traceable to a test.
- Use deterministic fakes (`MockEmbedder`, `MockEngineAdapter` in
  `tests/conftest.py`) for LLM/embedder adapters; never hit the real Ollama
  daemon in the test suite.
- Integration tests use temp directories, never the real `db/` artifacts.
- Raw OOXML/PDF builders in test files — no openpyxl/python-docx/pypdf writer
  dependency in tests.
- Protocol conformance tests for all adapter seams.
- Security tests: XXE defense, API key masking, path containment, zip-slip.
- Byte-for-byte preservation assertions for document formats (Excel, Word, PDF).
- A test must fail for the right reason and pass for the right reason.

| Marker | Scope | Budget |
|---|---|---|
| `unit` | Pure logic | < 100ms each |
| `adapter` | Adapter isolation, error translation, import boundary | < 500ms each |
| `integration` | Real SQLite/ChromaDB in temp dir | < 1s each |
| `e2e` | Full pipeline with mocked LLM | < 5s each |
| `eval` | Auditor evaluation matrix | may be slow |
| `slow` | > 5s | excluded from default CI run |

Default: `addopts = -m "not slow" --strict-markers --tb=short`.

---

## Boundaries

### Always

- Run `pytest --tb=short -q`, `ruff check src/ tests/`, and `mypy src/` before
  claiming work complete. **Evidence before assertions.**
- Read the relevant `openspec/specs/<capability>/spec.md` before implementing.
- Run `openspec validate --all` after changes; archive completed changes.
- Follow existing architecture and reuse existing components (SOLID, DRY, KISS,
  YAGNI).
- Prefer modifying existing code over creating new files.
- Validate all external input (corpus files, glossary JSON, CLI args, MCP
  requests); raise domain exceptions on invalid input.

### Ask first

- Changes to `requirements.txt` / `pyproject.toml` dependencies.
- Changes to `config.yaml` runtime defaults.
- Modifying behavior that a spec documents (requires an OpenSpec change
  proposal first).
- Edits to `.github/workflows/` or security/compliance controls.

### Never

- Commit secrets, API keys, or credentials.
- Make cloud LLM calls except the opt-in Gemini backend
  (`llm_backend: gemini`). No OpenAI, Anthropic, or other remote inference.
- Load a model > 8B params or exceed the 8 GB RAM ceiling.
- Use ChromaDB client/server mode or enable telemetry.
- Add a dependency published less than 7 days ago, or use floating ranges
  (`latest`, `*`, unbounded `>=`).
- Guess APIs or invent project conventions.
- Import concrete engines inside the pipeline — depend on protocols.
- Mutate state inside LangGraph conditional-edge routing functions.
- Reformat versioned prompt constants.
- Use a bare `except Exception:` without `logger.exception`/`logger.warning`
  (UI boundaries are the sole exception — see Coding Standards).
- Modify security policies or compliance controls to work around CI failures —
  escalate to the user.
- Force-push or rewrite shared history without explicit confirmation.

---

## OpenSpec Workflow

Specs are the contract. Every requirement in a spec MUST be preserved unless a
change proposal explicitly marks it `MODIFIED` or `REMOVED`.

**Workflow:** `Research → Plan → Tasks → Build → Verify`

1. **Research:** read relevant spec(s) and source; run `openspec list`; never
   assume behavior — verify by reading code.
2. **Plan:** create an OpenSpec change proposal for non-trivial work
   (`openspec new change <name> --goal "..."`), then write `proposal.md` →
   `specs/` (delta) → `design.md` → `tasks.md`. Validate before implementing.
3. **Tasks:** break into atomic, independent, testable, reviewable units.
4. **Build:** implement sequentially; follow architecture; reuse components.
5. **Verify:** tests + lint + types + `openspec validate --all`; archive
   completed changes; produce a verification summary with actual output.

Specs live in `openspec/specs/` (9 capabilities: `config`,
`translation_pipeline`, `knowledge_sources`, `infrastructure`, `interfaces`,
`application-logging`, `cli-commands`, `input-validation`, `ui-backends`).
`openspec/config.yaml` holds the project context, tech stack, and constraints.

---

## Security

- **No secrets in the repo.** Never commit credentials or connection strings.
- **No cloud calls by default.** Only the opt-in Gemini backend
  (`GEMINI_API_KEY`, lazy `google-genai` import) and the opt-in Iraqi legal
  web search (`web_search_enabled: false` by default) may reach the network.
- **Never log or expose secrets.** Run logs must not contain credentials;
  `GeminiEngineAdapter` redacts the API key in `__repr__` and errors.
- **Adapters are the trust boundary:** catch engine-specific errors, re-raise
  domain exceptions so nodes/CLI never see engine types.
- **Input validation surfaces** (enforced by `src/utils/` + component guards):
  path containment (`PathContainmentError`, exit 4), zip-slip prevention,
  XXE defense (`defusedxml`), XML injection prevention (`escape_xml_text`),
  document size caps (Excel 100 MiB / Word 50 MiB / PDF 100 MiB), atomic output
  (`.tmp` + `os.replace`), JSONL schema validation (Pydantic), MCP input caps
  + rate limiting (10 req/min), pywebview session token, legal-search URL
  allowlist (`moj.gov.iq`, `dijlex.com`, `urportal.ur.gov.iq`, `nlb.gov.iq`;
  max 3 redirect hops).
- Corpus data must come from **public official gazette publications**. With
  Ollama, no data leaves the host; with Gemini, only translation text is sent
  (never corpus/glossary wholesale).

---

## Verification Checklist

Run before claiming any task is complete. **Evidence before assertions.**

```powershell
pytest --tb=short -q          # tests
ruff check src/ tests/        # lint
mypy src/                     # type-check (strict)
radon cc src/ -a              # complexity
openspec validate --all       # specs
python -m src.app doctor      # smoke (requires Ollama)
```

- [ ] All relevant tests pass.
- [ ] `ruff check src/ tests/` clean.
- [ ] `mypy src/` clean (strict).
- [ ] No regressions; edge cases validated.
- [ ] `openspec validate --all` passes (0 failures).
- [ ] Specs reflect current behavior; change proposal archived if complete.
- [ ] No new dependencies without justification.
- [ ] Documentation updated where behavior changed.
- [ ] Verification summary produced with actual command output.

---

## Pull Request Guidelines

Follow `.github/PULL_REQUEST_TEMPLATE.md`. Conventional commits required.

**Commit format:**

```
<type>: <imperative summary>

<optional body explaining why, not what>

Generated with [Devin](https://devin.ai)

Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>
```

Types: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.

**CLI exit codes** (mapped by `handle_pipeline_errors` in
`src/utils/cli_errors.py`): 0 success · 1 generic · 2 Ollama/embedding
connection · 3 RAM guard · 4 path containment · 5 input validation · 6 I/O.

**PR checklist:** Summary describes *what* and *why*; change type marked;
issue linked (`Closes #<n>`); OpenSpec specs reviewed + `openspec validate --all`
passes + change proposal created/updated with `ADDED`/`MODIFIED`/`REMOVED`
markers; changes listed item-by-item; tests pass + lint/types clean on changed
files; new tests for new functionality; self-review done; docs updated; no new
dependencies without justification. If the PR does not modify behavior, explain
why no OpenSpec change is needed.

**Branching:** Do not push directly to `main` for non-trivial changes; open a
PR. Never force-push or rewrite shared history without explicit confirmation.

---

## Known Limitations

1. **macOS not supported by RAM guard** — Windows + Linux readers only;
   unsupported platforms return `None` (graceful degradation).
2. **No HITL in Tkinter UI** — only the pywebview web UI has human-in-the-loop
   review; Tkinter is the fallback.
3. **Direction detection is script-based** — `detect_direction()` counts
   Arabic vs Latin chars; may misclassify mixed-script text.
4. **Legal search HTML parsing is fragile** — BeautifulSoup scraping breaks on
   HTML changes; Dijlex often returns 403 (Cloudflare).
5. **Gemini embedding errors lack a dedicated timeout subclass** (unlike
   Ollama) — minor exception-hierarchy inconsistency.
6. **Two changes not yet archived** — `fix-build-and-spec-hygiene` and
   `add-pdf-word-translation` have all tasks complete but `openspec archive`
   not run.
7. **`top_k` default mismatch** — `config.yaml` (3) vs `AppConfig` default (8);
   `config.yaml` wins at runtime.
8. **`run.bat` hard-codes `.venv310`** — README quick start uses `.venv`.
9. **Some specs reference TBD Purpose** — `application-logging`,
   `cli-commands`, `input-validation`, `ui-backends` need Purpose fields
   updated.

---

## Definition of Done

A task is complete only when **all** of the following are true and backed by
evidence:

- [ ] **Specs:** relevant spec read; behavior change covered by a validated
      OpenSpec change proposal; change archived if complete.
- [ ] **Code:** follows architecture, conventions, and standards; reuses
      components; no dead code or unexplained TODOs.
- [ ] **Tests:** new behavior covered; all pass (`pytest --tb=short -q`); tests
      fail/pass for the right reasons.
- [ ] **Lint:** `ruff check src/ tests/` clean.
- [ ] **Types:** `mypy src/` clean (strict).
- [ ] **Complexity:** `radon cc src/ -a` acceptable (no new hotspots).
- [ ] **Specs valid:** `openspec validate --all` passes (0 failures).
- [ ] **No regressions:** edge cases validated; existing behavior preserved.
- [ ] **Constraints respected:** 8 GB RAM, no cloud calls by default (opt-in
      Gemini only), PersistentClient only, single in-flight request, no new
      unmaintained dependencies.
- [ ] **Docs updated:** README / AGENTS.md / specs reflect the new behavior.
- [ ] **Verification summary** produced with actual command output.

---

*This guide follows the [AGENTS.md open format](https://agents.md/) adopted by
OpenAI Codex, Cursor, Devin, Gemini CLI, and the broader AI coding agent
ecosystem. When it conflicts with a generic convention, this guide and the
OpenSpec specs win.*
