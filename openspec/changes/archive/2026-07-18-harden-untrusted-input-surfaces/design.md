## Context

The Iraqi Legal Translation Agent is offline-first and single-user, but it
accepts untrusted input at multiple surfaces: `.xlsx` workbooks, JSONL
batch files, MCP tool queries, and (via the pywebview bridge) arbitrary JS
strings. A 2026-07-18 security audit found that none of these surfaces
validate their input beyond basic type checks. The most severe issues are
in `excel.py`, which uses `xml.etree.ElementTree` (no XXE defense),
`zipfile` without zip-slip checks, and inserts LLM output into XML without
escaping — a chain that can corrupt workbooks or execute code in legacy
Excel.

The current architecture has no shared validation layer. Helpers like
`_resolve_path` are duplicated across `cli.py`, `diagnostics.py`, and
`tm_commands.py` with lazy-import workarounds. This change introduces a
new `src/utils/` package to host cross-cutting validation primitives
without creating a circular dependency on `interfaces`.

## Goals / Non-Goals

**Goals:**
- Close audit findings SEC-1 through SEC-11 (Critical) and SEC-15
  (Medium: subprocess path validation).
- Introduce a `src/utils/` package for shared validation primitives.
- Add `defusedxml` as the only new runtime dependency.
- Preserve every documented behavior in the source-of-truth specs; only
  add validation that fails fast on malformed/malicious input.
- Keep the change backward compatible at the config and CLI levels.

**Non-Goals:**
- Glossary ReDoS (SEC-12) — fixed in
  `improve-performance-and-maintainability` via Aho-Corasick.
- `tm.py:check_same_thread=False` (SEC-13) — fixed in
  `fix-resource-lifetimes`.
- Prompt injection (SEC-16) — documented as a known trust boundary; no
  code change in this proposal.
- Refactoring `cli.py` SRP or `web_ui.py:Api` SRP — those are in
  `improve-performance-and-maintainability`.
- Multi-user auth or networked deployment — explicitly a non-goal of the
  project (`AGENTS.md` §1.4).

## Decisions

### D1: New `src/utils/` package for shared validation

**Decision:** Create `src/utils/` with `paths.py`, `zip_safe.py`,
`xml_escape.py`, `jsonl_schema.py`, `rate_limit.py`.

**Rationale:** Validation helpers are needed by `interfaces`,
`knowledge_sources`, and `config`. Putting them in `interfaces` would
force `knowledge_sources` to depend on `interfaces`, breaking the acyclic
dependency graph (`AGENTS.md` §2). A `src/utils/` package depends on
nothing in `src/components/` and can be imported by everyone.

**Alternatives considered:**
- Put helpers in `src/config/` — rejected; config is for configuration,
not validation logic.
- Duplicate helpers per component — rejected; this is the current state
  and the audit flagged it as a DRY violation (MAINT-2).

### D2: `defusedxml` as a new runtime dependency

**Decision:** Add `defusedxml>=0.7,<1` to `requirements.txt` and
`pyproject.toml`. Replace `xml.etree.ElementTree.fromstring` with
`defusedxml.ElementTree.fromstring` in `excel.py`.

**Rationale:** `defusedxml` is the standard XXE defense for Python; it is
a drop-in replacement with no transitive dependencies and a 10+ year
maintenance history. The alternative (manually disabling entity expansion
on `xml.etree`) is fragile and version-dependent.

**Trade-off:** Adds one runtime dependency. Accepted: the security gain
outweighs the cost, and `defusedxml` is stdlib-quality.

### D3: Path containment against project root, not a fixed allowlist

**Decision:** `_validate_path_in_root(path, root=project_root())` resolves
the path and asserts `Path.resolve().is_relative_to(root.resolve())`.

**Rationale:** The project is single-user and offline; the user's intent
is "translate files I give you." Containment against the project root
prevents `../../etc/passwd` while still allowing files under the project
dir. A fixed allowlist would be too restrictive (users keep corpora
anywhere under the project).

**Trade-off:** A user who keeps input files outside the project root must
either move them or pass an absolute path inside the root. Documented in
README.

### D4: Session token for pywebview API, not full OAuth

**Decision:** `Api.__init__` generates a random `secrets.token_urlsafe(32)`
and injects it into the page via `evaluate_js`. Every `Api` method checks
the token via a `_require_token` decorator.

**Rationale:** pywebview runs in a single desktop window; there is no
multi-tenant threat model. A session token defeats XSS-driven bridge calls
and accidental cross-origin navigation without the complexity of OAuth.

### D5: Atomic Excel output via `os.replace`

**Decision:** `translate_excel` writes to `<output>.tmp`, then
`os.replace(tmp, output)` on success.

**Rationale:** `os.replace` is atomic on Windows and POSIX. Prevents
partial-workbook corruption if the process crashes mid-write. No cost.

### D6: JSONL schema via Pydantic, not hand-rolled validation

**Decision:** `BatchRecord` and `ParallelPair` are Pydantic models in
`src/utils/jsonl_schema.py`. Parse with `model_validate_json(line)`.

**Rationale:** Pydantic is already a runtime dependency (`config.py`).
Reusing it for JSONL validation gives us type coercion, max-length
constraints, and clear error messages for free.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| `defusedxml` adds a dependency that could go unmaintained | Pin `>=0.7,<1`; it has been stable since 2013. |
| Path containment breaks a user's existing workflow that reads files outside the project root | Document in README §5.6; users can symlink or move files. |
| Session token breaks JS calls that don't send it | The token is injected at page load; the frontend is updated in the same change. |
| `max_xlsx_bytes=100 MB` is too low for some real workbooks | Configurable in `config.yaml`; default is a safe ceiling for the 8 GB RAM target. |
| Rate limiter on MCP tools breaks IDE integrations that batch-search | 10 req/60s is generous for interactive use; configurable later. |
| `follow_redirects=False` in `legal_search` breaks sites that redirect HTTP→HTTPS | Manual redirect resolution re-issues HTTPS against the allowlist. |

## Target directory tree (new and modified files)

```
src/
  utils/                          # NEW package
    __init__.py
    paths.py                      # _validate_path_in_root
    zip_safe.py                   # _validate_zip_path
    xml_escape.py                 # escape_xml_text
    jsonl_schema.py               # BatchRecord, ParallelPair
    rate_limit.py                 # TokenBucket
  components/
    interfaces/
      excel.py                    # MODIFIED: defusedxml, zip-slip, escape, caps, atomic write
      cli.py                      # MODIFIED: path containment on translate/batch/excel
      orchestration.py            # MODIFIED: _resolve_input containment, _process_batch schema
      tm_commands.py              # MODIFIED: JSONL schema in tm_build_parallel, tm_add_parallel
      mcp_server.py               # MODIFIED: query/max_results caps, rate limiter
      web_ui.py                   # MODIFIED: session token, origin pin
      web_frontend.py             # MODIFIED: innerHTML → textContent audit
    knowledge_sources/
      legal_search.py             # MODIFIED: host allowlist, redirect containment, JSON-LD cap
    translation_pipeline/
      exceptions.py               # MODIFIED: + LegalSearchBlockedError, PathContainmentError, InputValidationError
  config/
    models.py                     # MODIFIED: ExcelConfig.max_xlsx_bytes, max_segments
config.yaml                       # MODIFIED: excel.max_xlsx_bytes, excel.max_segments defaults
requirements.txt                  # MODIFIED: + defusedxml>=0.7,<1
pyproject.toml                    # MODIFIED: + defusedxml>=0.7,<1
```

## Inter-component communication

`src/utils/` is the lowest layer: it imports only stdlib + `pydantic`.
Every component may import from it. No component imports `utils` from
another component — `utils` is a leaf in the dependency graph.

```
src/utils  ◀──  config, infrastructure, knowledge_sources, translation_pipeline, interfaces
```

The new exceptions (`LegalSearchBlockedError`, `PathContainmentError`,
`InputValidationError`) live in `translation_pipeline/exceptions.py`
(inside the existing `LegalTranslationError` hierarchy) so the existing
"nodes and the CLI only ever see domain exceptions" rule
(`AGENTS.md` §2) is preserved.
