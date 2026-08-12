## 1. Foundation: `src/utils/` package + new exceptions

- [x] 1.1 Create `src/utils/__init__.py` (empty, with docstring)
- [x] 1.2 Create `src/utils/paths.py` with `validate_path_in_root(path: Path, root: Path) -> Path` that resolves and asserts `is_relative_to`; raises `PathContainmentError` on violation
- [x] 1.3 Create `src/utils/zip_safe.py` with `validate_zip_path(name: str) -> str` that rejects absolute paths, `..` segments, and backslash escapes; raises `InputValidationError`
- [x] 1.4 Create `src/utils/xml_escape.py` with `escape_xml_text(text: str) -> str` wrapping `xml.sax.saxutils.escape`
- [x] 1.5 Create `src/utils/jsonl_schema.py` with Pydantic `BatchRecord` (input: str max 10000, direction: Literal["ar-en","en-ar"]) and `ParallelPair` (source_sentence, target_sentence max 10000, source_lang="ar", target_lang="en")
- [x] 1.6 Create `src/utils/rate_limit.py` with `TokenBucket(rate: float, capacity: int)` thread-safe token bucket
- [x] 1.7 Add `LegalSearchBlockedError`, `PathContainmentError`, `InputValidationError` to `src/components/translation_pipeline/exceptions.py` as `LegalTranslationError` subclasses
- [x] 1.8 Add `src.utils` to `pyproject.toml` `[tool.setuptools] packages`
- [x] 1.9 Verify: `python -c "import src.utils.paths, src.utils.zip_safe, src.utils.xml_escape, src.utils.jsonl_schema, src.utils.rate_limit"` succeeds
- [x] 1.10 Verify: `ruff check src/utils/` is clean

## 2. Excel OOXML hardening

- [x] 2.1 Add `defusedxml>=0.7,<1` to `requirements.txt` and `pyproject.toml` `[project.dependencies]`
- [x] 2.2 `pip install defusedxml` and verify import works
- [x] 2.3 In `excel.py`, replace `import xml.etree.ElementTree as ET` with `from defusedxml.ElementTree import fromstring` (alias as `ET_fromstring`); update both call sites (lines 259, 321)
- [x] 2.4 In `excel.py:extract_translatable_strings` and `patch_strings`, call `validate_zip_path(info.filename)` on every zip entry before read/write
- [x] 2.5 In `excel.py:_patch_part`, wrap every `el.text = new` assignment with `el.text = escape_xml_text(new)`
- [x] 2.6 In `excel.py:translate_excel`, add `max_xlsx_bytes` check: `if input_path.stat().st_size > cfg.excel.max_xlsx_bytes: raise InputValidationError(...)`
- [x] 2.7 In `excel.py:translate_excel`, after `extract_translatable_strings`, check `if len(segments) > cfg.excel.max_segments: raise InputValidationError(...)`
- [x] 2.8 In `excel.py:translate_excel`, write output atomically: write to `output_path.with_suffix(output_path.suffix + ".tmp")` then `os.replace(tmp, output_path)`
- [x] 2.9 Add `ExcelConfig.max_xlsx_bytes: int = 100 * 1024 * 1024` and `ExcelConfig.max_segments: int = 10000` to `src/config/models.py` with validators (`max_xlsx_bytes >= 1_048_576`, `max_segments >= 100`)
- [x] 2.10 Add `excel.max_xlsx_bytes` and `excel.max_segments` defaults to `config.yaml`
- [x] 2.11 Verify: existing Excel tests still pass (`pytest tests/test_excel.py tests/test_web_ui_excel.py -q`)
- [x] 2.12 Add new tests: `test_xxe_rejected` (entity expansion in sharedStrings is refused), `test_zip_slip_rejected` (entry with `../` is refused), `test_xml_injection_escaped` (translation containing `</t><evil/>` is escaped), `test_oversized_xlsx_rejected`, `test_too_many_segments_rejected`, `test_atomic_output_no_partial_on_crash`

## 3. CLI path containment

- [x] 3.1 In `cli.py:translate`, validate `input_arg` via `validate_path_in_root` before `_resolve_input`; on `PathContainmentError`, print error and exit code 4
- [x] 3.2 In `cli.py:batch`, validate both `input` and `out` paths; exit code 4 on violation
- [x] 3.3 In `cli.py:excel`, validate both `input` and `out` paths; exit code 4 on violation
- [x] 3.4 In `orchestration.py:_resolve_input`, add `validate_path_in_root` call (defense in depth — CLI already checks, but `_resolve_input` is also called from UI)
- [x] 3.5 Verify: `pytest tests/test_cli.py -q` passes
- [x] 3.6 Add new tests: `test_translate_rejects_path_traversal`, `test_batch_rejects_path_traversal_output`, `test_excel_rejects_path_traversal`

## 4. MCP server input validation + rate limiting

- [x] 4.1 In `mcp_server.py`, add `_validate_query(query: str) -> str` that raises `InputValidationError` if `len(query) > 500` or empty
- [x] 4.2 In `mcp_server.py`, add `_validate_max_results(n: int) -> int` that clamps to `[1, 100]`
- [x] 4.3 In `mcp_server.py`, instantiate a module-level `TokenBucket(rate=10/60, capacity=10)` per tool (or one shared bucket)
- [x] 4.4 Wrap each `@mcp.tool()` function to call `_validate_query`, `_validate_max_results`, and the token bucket before delegating
- [x] 4.5 Verify: `pytest tests/test_mcp_server.py -q` passes
- [x] 4.6 Add new tests: `test_query_too_long_rejected`, `test_max_results_clamped`, `test_rate_limiter_returns_429_after_burst`

## 5. pywebview API + frontend hardening

- [x] 5.1 In `web_ui.py:Api.__init__`, generate `self._token = secrets.token_urlsafe(32)` and expose via `get_token()` (called once at page load)
- [x] 5.2 In `web_ui.py:Api`, add `_require_token` decorator that compares `token` arg to `self._token`; raises `PermissionError` on mismatch
- [x] 5.3 Apply `_require_token` to every public `Api` method that mutates state or starts a job (`translate`, `translate_excel`, `submit_review`, `approve_review`, `open_in_explorer`, `pick_excel_input`, `pick_excel_output`)
- [x] 5.4 In `web_ui.py:launch_ui`, after `webview.create_window`, inject the token into the page via `window.evaluate_js(f"window.__SESSION_TOKEN='{token}';")`
- [x] 5.5 In `web_frontend.py`, update every `pywebview.api.<method>(...)` call to pass `window.__SESSION_TOKEN` as the first arg
- [x] 5.6 In `web_frontend.py`, audit every `element.innerHTML =` assignment: if the value contains translation/provenance/audit-trace content, replace with `element.textContent =` or `element.innerHTML = escapeHtml(value)`. Static markup may stay `innerHTML`.
- [x] 5.7 Add an `escapeHtml(s)` JS helper to `web_frontend.py` (escapes `&<>"'`)
- [x] 5.8 Verify: `pytest tests/test_web_ui_excel.py -q` passes (update tests to send the token)
- [x] 5.9 Add new tests: `test_api_rejects_missing_token`, `test_api_rejects_wrong_token`, `test_frontend_escape_html_escapes_all_special_chars`

## 6. JSONL schema validation

- [x] 6.1 In `orchestration.py:_process_batch`, replace `record = json.loads(line)` with `record = BatchRecord.model_validate_json(line)`; on `ValidationError`, log line number and skip
- [x] 6.2 In `tm_commands.py:tm_build_parallel` and `tm_add_parallel`, replace manual JSONL parsing with `ParallelPair.model_validate_json(line)`; on `ValidationError`, print error and exit code 5
- [x] 6.3 Verify: `pytest tests/test_cli.py tests/test_tm_parallel.py -q` passes (update fixtures if needed)
- [x] 6.4 Add new tests: `test_batch_skips_malformed_record`, `test_tm_build_parallel_rejects_malformed_jsonl`, `test_batch_record_rejects_oversized_input`

## 7. Legal search hardening

- [x] 7.1 In `legal_search.py`, add `_ALLOWED_HOSTS: frozenset[str]` with `moj.gov.iq`, `www.moj.gov.iq`, `dijlex.com`, `www.dijlex.com`, `urportal.ur.gov.iq`, `www.urportal.ur.gov.iq`, `nlb.gov.iq`, `www.nlb.gov.iq`
- [x] 7.2 Add `_validate_url(url: str) -> str` that parses the URL, checks `urllib.parse.urlparse(url).hostname` against `_ALLOWED_HOSTS`, raises `LegalSearchBlockedError` on mismatch
- [x] 7.3 In `_fetch_html` and `_post_html`, set `follow_redirects=False`; on 3xx response, manually resolve the redirect URL through `_validate_url` and re-issue (max 3 hops)
- [x] 7.4 In `search_ur_portal`, cap `len(script.string or "")` at 1_048_576 before `json.loads`; skip oversized scripts
- [x] 7.5 Verify: `pytest tests/test_web_search.py -q` passes
- [x] 7.6 Add new tests: `test_legal_search_rejects_non_allowlisted_host`, `test_legal_search_blocks_cross_domain_redirect`, `test_legal_search_skips_oversized_jsonld`

## 8. Documentation + final verification

- [x] 8.1 Update `README.md` §5.3 to mention `defusedxml` install and the new path-containment rule
- [x] 8.2 Update `README.md` §5.6 to document that `--input`/`--out` must be inside the project root
- [x] 8.3 Update `AGENTS.md` §12 (Security Guidelines) with the new validation surfaces
- [x] 8.4 Run `ruff check src/ tests/` — must be clean
- [x] 8.5 Run `mypy src/` — must not introduce new errors
- [x] 8.6 Run `pytest --tb=short -q` — full suite green (excluding `slow`)
- [x] 8.7 Run `openspec validate harden-untrusted-input-surfaces` — must pass
- [x] 8.8 Run `openspec validate --all` — must pass
