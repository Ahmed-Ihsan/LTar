## Why

A production-grade security audit (2026-07-18) surfaced 8 Critical and 3 High
findings on the untrusted-input surfaces of the Iraqi Legal Translation Agent.
Every input the system is asked to translate, search, or batch-process flows
through a code path that currently trusts its input:

- `excel.py` parses OOXML with `xml.etree.ElementTree.fromstring` (no XXE
  defense), uses `info.filename` directly in `zipfile` reads/writes (zip-slip),
  inserts LLM-produced text into XML nodes without escaping (XML injection),
  and has no file-size or segment-count caps (DoS on an 8 GB RAM target).
- `cli.py` `translate`/`batch`/`excel` accept `--input`/`--out` paths with no
  containment check, so `../../etc/passwd` is happily read or written.
- `mcp_server.py` tools accept arbitrary-length `query` strings and unbounded
  `max_results`, with no rate limiting.
- `web_ui.py:Api` exposes a pywebview bridge with no auth, CSRF token, or
  origin pin; `web_frontend.py` inserts translation output via `innerHTML`.
- `orchestration.py:_process_batch` and `tm_commands.py` deserialize JSONL
  with `json.loads` + string key indexing and no schema validation.
- `legal_search.py` fetches arbitrary URLs with `follow_redirects=True` and
  no allowlist (SSRF), and `json.loads`es untrusted `<script
  type="application/ld+json">` content with no size limit.

These are exploitable from any input the system is asked to process. Because
the system is offline and single-user, the *likelihood* is lower than a
cloud product, but the *impact* (arbitrary file read/write, code execution
via malicious `.xlsx`, DoS that violates the 8 GB RAM ceiling) is identical.
Defense in depth is the correct posture: validate at every trust boundary.

## What Changes

This change hardens every untrusted-input surface without altering the
happy-path behavior documented in the source-of-truth specs.

1. **Excel OOXML hardening** (`excel.py`):
   - Switch `ET.fromstring` → `defusedxml.ElementTree.fromstring` (XXE
     defense, drop-in replacement).
   - Validate every `info.filename` against zip-slip: reject absolute paths
     and any path containing `..` segments or backslashes that escape the
     archive root.
   - Escape translated text with `xml.sax.saxutils.escape` before assigning
     to `el.text` (XML injection defense).
   - Add `max_xlsx_bytes` (default 100 MB) and `max_segments` (default
     10 000) caps to `ExcelConfig`; enforce both in `translate_excel` and
     reject early with a clear error.
   - Write output atomically: write to `<output>.tmp` then `os.replace` to
     the final path only on success.

2. **CLI path containment** (`cli.py`, `orchestration.py:_resolve_input`):
   - Add a `_validate_path_in_root(path, root)` helper that resolves the
     path and asserts `is_relative_to(root)`.
   - Apply to `--input` (translate, batch, excel) and `--out` (batch,
     excel) for both read and write operations.
   - On violation, print a clear error and exit with code 4 (new
     "path-containment violation" code; see also the
     `improve-performance-and-maintainability` change for full exit-code
     standardization).

3. **MCP server input validation** (`mcp_server.py`):
   - Cap `len(query) <= 500` and `1 <= max_results <= 100` on every tool.
   - Add a per-session token-bucket rate limiter (max 10 requests / 60 s
     per tool) that returns HTTP 429-style JSON on overflow.

4. **pywebview API + frontend hardening** (`web_ui.py`, `web_frontend.py`):
   - Generate a session token at `Api.__init__`; require it on every `Api`
     method via a `_require_token` decorator. The token is injected into
     the page at load time and sent with every `pywebview.api.*` call.
   - Pin `webview.windows[0].evaluate_js` to only accept calls whose
     `window.origin` matches the loaded resource origin.
   - Audit `web_frontend.py` and replace every `innerHTML` assignment that
     inserts translation/provenance/audit-trace content with `textContent`
     or an `escapeHtml` helper. Static markup may still use `innerHTML`.

5. **JSONL schema validation** (`orchestration.py:_process_batch`,
   `tm_commands.py:tm_build_parallel`, `tm_add_parallel`):
   - Add Pydantic models `BatchRecord` (`input: str`, `direction:
     Literal["ar-en","en-ar"]`) and `ParallelPair` (`source_sentence: str`,
     `target_sentence: str`, `source_lang: str = "ar"`, `target_lang: str =
     "en"`) with per-field max-length caps (10 000 chars).
   - Replace `json.loads(line) + record["input"]` with
     `BatchRecord.model_validate_json(line).input`.
   - On validation failure, log the line number and skip (batch) or exit
     with code 5 (tm commands, preserving current behavior).

6. **Legal search hardening** (`legal_search.py`):
   - Add a `_ALLOWED_HOSTS` allowlist (`moj.gov.iq`, `dijlex.com`,
     `urportal.ur.gov.iq`, `www.nlb.gov.iq`, and their `www.` variants).
   - Validate every fetched URL's host against the allowlist; raise a new
     `LegalSearchBlockedError` (a `LegalTranslationError` subclass) on
     mismatch. Disable cross-domain redirects by setting
     `follow_redirects=False` and resolving redirects manually against the
     allowlist.
   - Cap `<script type="application/ld+json">` content length at 1 MB
     before `json.loads`.

## Capabilities

### New Capabilities

- `input-validation`: Cross-cutting input-validation primitives shared by
  the interfaces and knowledge_sources components — path containment,
  zip-slip check, XML escape helper, JSONL schema models, query-length /
  rate-limit helpers. Lives in a new `src/utils/` package so it can be
  imported by every component without creating a circular dependency on
  `interfaces`.

### Modified Capabilities

- `interfaces`: Excel OOXML parsing/patching, CLI path handling, MCP tool
  signatures, pywebview `Api` auth, web frontend DOM insertion, and JSONL
  batch/TM parsing all gain validation requirements.
- `knowledge_sources`: `legal_search` gains a host allowlist, redirect
  containment, and JSON-LD size cap.
- `config`: `ExcelConfig` gains `max_xlsx_bytes` and `max_segments` fields
  with validators.

## Impact

**Affected code:**
- `src/components/interfaces/excel.py` (XXE, zip-slip, XML escape, caps,
  atomic write)
- `src/components/interfaces/cli.py` (path containment on `translate`,
  `batch`, `excel`)
- `src/components/interfaces/orchestration.py` (`_resolve_input`,
  `_process_batch` JSONL schema)
- `src/components/interfaces/tm_commands.py` (JSONL schema in
  `tm_build_parallel`, `tm_add_parallel`)
- `src/components/interfaces/mcp_server.py` (query/max_results caps, rate
  limiter)
- `src/components/interfaces/web_ui.py` (session token, origin pin)
- `src/components/interfaces/web_frontend.py` (`innerHTML` → `textContent`
  audit)
- `src/components/knowledge_sources/legal_search.py` (host allowlist,
  redirect containment, JSON-LD size cap)
- `src/config/models.py` (`ExcelConfig.max_xlsx_bytes`,
  `max_segments` + validators)
- `config.yaml` (new `excel.max_xlsx_bytes` and `excel.max_segments`
  defaults)
- New: `src/utils/__init__.py`, `src/utils/paths.py`,
  `src/utils/zip_safe.py`, `src/utils/xml_escape.py`,
  `src/utils/jsonl_schema.py`, `src/utils/rate_limit.py`
- New: `src/components/translation_pipeline/exceptions.py` gains
  `LegalSearchBlockedError`, `PathContainmentError`,
  `InputValidationError`.

**New dependencies:**
- `defusedxml>=0.7,<1` (drop-in replacement for `xml.etree.ElementTree`;
  stdlib-quality, no transitive deps). Added to both `requirements.txt`
  and `pyproject.toml` `[project.dependencies]`.

**APIs:**
- No public CLI command signatures change. Two new exit codes are
  introduced (4 = path-containment violation, 5 = JSONL validation
  error); existing codes 0/1/2/3 are unchanged.
- `ExcelConfig` gains two fields with defaults — existing `config.yaml`
  files without them continue to work (defaults applied).

**Specs:**
- `interfaces/spec.md` gains MODIFIED requirements for Excel XML
  extraction/patching, CLI subcommands, MCP server, pywebview UI, and
  ADDED requirements for JSONL schema validation and CLI path
  containment.
- `knowledge_sources/spec.md` gains a MODIFIED requirement for
  `legal_search` (allowlist + size cap).
- `config/spec.md` gains a MODIFIED requirement for `ExcelConfig` (two
  new fields).
- New `input-validation/spec.md` describes the shared primitives.

**Migration path:**
- All changes are backward compatible at the config and CLI levels.
- `defusedxml` is a new runtime dependency; users must re-run
  `pip install -r requirements.txt` (documented in README §5.3).
- No data migration; no DB schema changes.

**Rollback plan:**
- Revert the commit; remove `defusedxml` from `requirements.txt`. No
  persistent state is touched by this change, so rollback is a clean
  `git revert`. The new `src/utils/` package can be left in place (it is
  not imported by anything else) or removed in the same revert.

**Security impact:**
- Closes audit findings SEC-1 through SEC-11 (Critical) and SEC-12
  remains open (glossary ReDoS — moved to
  `improve-performance-and-maintainability` because the fix is Aho-Corasick,
  not a validation tweak).
- This change is the security baseline required before any production
  deployment.
