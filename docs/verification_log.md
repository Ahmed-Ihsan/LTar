# Verification Log

Machine-checkable verification results for the Iraqi Legal Translation Agent. Each entry records the task ID, date, command, observed output, and pass/fail verdict.

---

## Phase 1 — Environment & Ollama Setup

### 1.2.1 — Ollama install on Windows

- **Date:** 2026-07-01
- **Command:** `ollama --version`
- **Output:** `Warning: could not connect to a running Ollama instance` / `Warning: client version is 0.22.0`
- **Exit code:** 0
- **Verdict:** PASS. Ollama 0.22.0 is installed at `C:\Users\demha\AppData\Local\Programs\Ollama\ollama.exe` on Windows 10.0.26200. The "could not connect" warning is benign — it only means the daemon was not yet running when the CLI checked; the version string is still printed and the command exits 0. (A newer release, v0.31.1, is available but not required.)

### 1.2.2 — Pull qwen2.5:7b-instruct-q5_K_M and nomic-embed-text

- **Date:** 2026-07-01
- **Commands:**
  - `ollama pull qwen2.5:7b-instruct-q5_K_M` → exit 0 (5.4 GB downloaded)
  - `ollama pull nomic-embed-text` → exit 0 (274 MB downloaded)
- **Verify command:** `ollama list`
- **Output:**
  ```
  NAME                          ID              SIZE      MODIFIED
  qwen2.5:7b-instruct-q5_K_M    a1040ddd2b49    5.4 GB    2026-07-01
  nomic-embed-text:latest       0a109f422b47    274 MB    2026-07-01
  ```
- **Verdict:** PASS. Both models are present in the local Ollama model store.

### 1.2.3 — Model memory footprint ≤ 3.2 GB RSS while idle after warmup

- **Date:** 2026-07-01
- **Warmup command:** `ollama run qwen2.5:7b-instruct-q5_K_M "Reply with the single word: ready"` → model replied `ready`, exit 0.
- **`ollama ps` output (captured immediately after warmup, model idle/loaded):**
  ```
  NAME                          ID              SIZE      PROCESSOR    CONTEXT    UNTIL
  qwen2.5:7b-instruct-q5_K_M    a1040ddd2b49    5.6 GB    100% GPU     4096       4 minutes from now
  ```
- **System-RAM RSS (WorkingSet) of Ollama processes, measured via `Get-CimInstance Win32_Process`:**

  | PID   | Name            | WS (MB) | Role                                      |
  |-------|-----------------|---------|-------------------------------------------|
  | 1972  | ollama.exe      | 776.7   | `ollama.exe runner --model ...` (LLM runner, model on GPU) |
  | 3340  | ollama.exe      | 103.2   | `ollama.exe serve` (API server)           |
  | 25480 | ollama app.exe  | 33.5    | `ollama app.exe --hide --fast-startup` (tray GUI) |
  |       | **Total RSS**   | **913.4** |                                           |

- **Recorded RSS value:** **913.4 MB (0.89 GB)**
- **Verdict:** PASS. 913.4 MB ≤ 3.2 GB (3200 MB).

  **Important caveat — GPU offloading.** The `ollama ps` SIZE column reports 5.6 GB, but the PROCESSOR column shows `100% GPU`, meaning the model weights + KV cache reside entirely in GPU VRAM, not in system RAM. Consequently the system-RAM RSS of the Ollama processes is only ~913 MB. This machine has a discrete GPU with sufficient VRAM, so the 8 GB system-RAM budget is easily met here.

  On a **CPU-only** 8 GB target machine (no GPU), the same 7B q5_K_M model would load fully into system RAM at ~5.4–5.6 GB RSS, which would **exceed** the 3.0 GB Ollama-LLM line item in the `offline-architecture` RAM budget and the 3.2 GB threshold in this task. For the CPU-only target, either (a) a smaller quantization / model, (b) partial GPU offload, or (c) a revised RAM budget must be chosen before Phase 1 exit. The `doctor` command (task 1.3.3) should detect and report the GPU-vs-CPU offload mode so this is visible at runtime.

### 1.3.1 — Create directory tree

- **Date:** 2026-07-01
- **Command:** `python -c "import os; [os.makedirs(p, exist_ok=True) for p in ['data/glossary','data/corpus','data/raw','db','src','tests']]"`
- **Exit code:** 0
- **Directories confirmed present:** `data/glossary`, `data/corpus`, `data/raw`, `db/`, `src/`, `tests/`.
- **Verdict:** PASS. `src/` and `src/__init__.py` already existed from Phase 1.1; the remaining directories were created idempotently with `exist_ok=True`.

### 1.3.2 — Create stub modules

- **Date:** 2026-07-01
- **Command:** `python -c "import src"`
- **Exit code:** 0 (prints `import src OK`)
- **Modules created (8 stubs, each with a single-responsibility docstring):**
  - `src/glossary.py` — glossary load / normalize / scan (Phase 2)
  - `src/ingestion.py` — corpus parse / chunk / token count (Phase 2)
  - `src/embeddings.py` — Ollama embedding adapter (Phase 2)
  - `src/retrieval.py` — ChromaDB store / query (Phase 2)
  - `src/graph.py` — LangGraph topology (Phase 3)
  - `src/nodes.py` — preprocess / translate / audit nodes (Phase 3)
  - `src/state.py` — `TranslationState` TypedDict (Phase 3)
  - `src/prompts.py` — versioned prompt constants (Phase 3)
- **Pre-existing (Phase 1.1):** `src/__init__.py`, `src/config.py`, `src/cli.py`.
- **Aggregate import check:** `import src.config, src.glossary, src.ingestion, src.embeddings, src.retrieval, src.graph, src.nodes, src.state, src.prompts, src.cli` → all 10 modules import OK.
- **Verdict:** PASS. Every stub uses `from __future__ import annotations` (clean-code §1.1) and a docstring naming its single responsibility per engineering-principles §1.1 and the implementing phase.

### 1.3.3 — `doctor` command

- **Date:** 2026-07-01
- **Command:** `python -m src.cli doctor`
- **Host:** Windows 10.0.26200, 31.7 GB RAM, discrete GPU (qwen2.5 7B q5_K_M loads 100% into VRAM).
- **Output (model warmed up, GPU offload active):**
  ```
  doctor: running environment checks
    [OK]   Ollama daemon reachable: connected, /api/tags responded
    [OK]   Required models present: qwen2.5:7b-instruct-q5_K_M + nomic-embed-text both installed
    [FAIL] ChromaDB directory exists: not found: ...\db\chroma (run `python -m src.ingestion --rebuild`)
    [FAIL] Glossary SQLite populated: not found: ...\db\glossary.sqlite (run `python -m src.ingestion --rebuild`)
    [OK]   RAM headroom estimate: total 31.7 GB; fixed budget 3.9 GB (LLM 0.9 GB, offload: 100% GPU); headroom ~27.8 GB
  ```
- **Exit code:** 1 (2 of 5 checks fail because Phase 2 ingestion has not yet created the DB stores — expected at this phase).
- **Negative-path verification (Ollama unreachable):** a temp `config.yaml` with `ollama_host: http://127.0.0.1:9999` produced clear red `[FAIL]` lines for the Ollama and model checks with exit 1, confirming the "clear red failure" requirement.
- **Checks implemented (5):**
  1. **Ollama daemon reachable** — `client.list()`; catches `ConnectionError`/`OSError`.
  2. **Required models present** — compares `cfg.llm_model` + `cfg.embed_model` against `client.list()`. Model names are canonicalized so an untagged name (`nomic-embed-text`) matches Ollama's `:latest` default (`nomic-embed-text:latest`).
  3. **ChromaDB directory exists** — `db/chroma/` is a directory.
  4. **Glossary SQLite populated** — `db/glossary.sqlite` exists, is readable (read-only URI connect), and contains ≥ 1 table.
  5. **RAM headroom estimate** — reads total/available RAM via stdlib `ctypes` (`GlobalMemoryStatusEx`) on Windows and `/proc/meminfo` on Linux (no `psutil` dependency); detects GPU-vs-CPU offload from `ollama ps` `size_vram`/`size` ratio (`100% GPU` / `CPU-only` / `partial GPU` / `not loaded`); computes headroom against the README.md §3 budget and flags the CPU-only 7B-q5 budget-exceedance caveat from §1.2.3 above.
- **Verdict:** PASS. The command prints a green `[OK]` for each passing check and a clear red `[FAIL]` for each failing check, with a non-zero exit code when any check fails. The two DB failures are expected and will turn green after Phase 2 ingestion (`python -m src.ingestion --rebuild`).
- **Phase 1 Exit Criterion status:** NOT YET MET on the 8 GB target machine. On this 31.7 GB GPU host all environment checks pass except the two Phase-2 DB stores. The Phase 1 exit criterion (`python -m src.cli doctor` passes all checks on the 8 GB target) requires (a) running Phase 2 ingestion to populate `db/chroma/` and `db/glossary.sqlite`, and (b) verifying on the actual 8 GB target — where the `doctor` RAM check will surface the CPU-only offload warning if no GPU is present.

---

## Phase 2 — Vector DB & Glossary Ingestion

### 2.1.1 — Glossary loader + SQLite index

- **Date:** 2026-07-01
- **Command:** `.venv310\Scripts\python.exe -m pytest tests/test_glossary_sqlite.py -v`
- **Host:** Windows 10.0.26200; Python 3.10.11 (`.venv310` — host has no Python 3.11; `from __future__ import annotations` enables PEP 604 unions on 3.10 per Phase 1 precedent).
- **Output:** 4 passed (`test_load_and_query_both_terms`, `test_load_and_query_both_terms`, `test_load_index_from_db_and_scan`, `test_rebuild_is_idempotent`, `test_missing_db_raises`).
- **Verify step:** loaded a 2-term sample JSON (`عقد البيع` ar→en + `contract of sale` en→ar) via `load_glossary_files`, wrote `build_sqlite_index(terms, tmp/db/glossary.sqlite)`, queried `SELECT source_term FROM glossary_terms WHERE source_term_norm IN (?, ?)` → both terms retrievable.
- **Verdict:** PASS. `src/glossary.py` implements `load_glossary_files(glob) -> list[Term]` (sorted paths, deterministic global `file_order`) and `build_sqlite_index(terms, db_path)` (idempotent DROP+CREATE of `glossary_terms`, `source_term_norm` lookup index). `load_glossary_index(db_path) -> GlossaryIndex` reads the DB back read-only. New `src/exceptions.py` holds the domain hierarchy (clean-code §3.1).

### 2.1.2 — Normalization (Arabic / English)

- **Date:** 2026-07-01
- **Command:** `.venv310\Scripts\python.exe -m pytest tests/test_glossary_normalize.py -v`
- **Output:** 14 passed.
- **Verify step:** `normalize_arabic("العَقْد") == normalize_arabic("العقد")` asserted in `test_diacritics_vs_plain_are_equal` → PASS.
- **Verdict:** PASS. `normalize_arabic` strips tashkeel (U+064B–U+0652) + tatweel (U+0640), folds أإآ→ا and ى→ي; `normalize_english` lowercases, collapses whitespace, strips trailing punctuation. Both pure + idempotent. Verbatim `source_term` and normalized `source_term_norm` are both stored in the `Term` dataclass and SQLite.

### 2.1.3 — Glossary scan (longest-match + conflict resolution)

- **Date:** 2026-07-01
- **Command:** `.venv310\Scripts\python.exe -m pytest tests/test_glossary_scan.py tests/test_glossary_conflict.py -v`
- **Output:** 13 passed (9 scan + 4 conflict).
- **Verify step:** overlapping-term test `test_longest_match_wins_over_substring` returns the longer match (`عقد البيع`, not `عقد`); priority-override test `test_higher_priority_wins_on_same_span` returns `court` (priority 10) over `tribunal` (priority 5) → both PASS.
- **Verdict:** PASS. `GlossaryIndex.scan` compiles one diacritic-tolerant regex per source language (alternation of normalized forms ordered longest-first) so the longest viable term wins at each start position; `re.finditer` yields non-overlapping spans in left-to-right order. Same-span conflicts resolve per DATA_SPEC §2.4: priority → longer verbatim `source_term` → non-null `law_ref` → earliest `file_order`. Char offsets index the original (un-normalized) text, so `text[char_start:char_end]` returns the verbatim matched span including any diacritics. Word boundaries: a following-letter lookahead blocks stem-in-suffixed-token matches (e.g. `عقد` inside `العقدة`); the preceding lookbehind blocks letters except Arabic proclitics (و ب ل ف) so `الالتزام` still matches inside `والالتزام`. `glossary_scan` is an alias of the canonical `scan_glossary_hits` (engineering-principles §2.1.2 naming; DRY).

### 2.1.4 — Validation at ingestion

- **Date:** 2026-07-01
- **Command:** `.venv310\Scripts\python.exe -m pytest tests/test_glossary_validation.py -v`
- **Output:** 8 passed.
- **Verify step:** `test_malformed_json_rejected` feeds `{ not valid json ` → `GlossaryValidationError` raised matching `"invalid JSON"`; `test_error_lists_offending_field_and_file` asserts the message contains both the file name and the missing field name → PASS.
- **Verdict:** PASS. `load_glossary_file` enforces every DATA_SPEC §2.5 rule: missing required file field (`domain`/`version`/`last_updated`), missing required term field (`source_term`/`source_lang`/`target_term`/`target_lang`/`law_ref`), `source_lang == target_lang` no-op entry, empty/whitespace `source_term`/`target_term`, empty `terms[]`, malformed JSON (with line/col), and intra-file duplicate `(source_term_norm, source_lang, target_lang)` → `GlossaryConflictError`. All errors descend from `GlossaryError` (clean-code §3.1) and name the offending field + file path. The library raises domain exceptions rather than calling `sys.exit`; the process-exit-1 behaviour required by the verify wording is the ingestion command's job (Phase 2.3 `src.ingestion`), which will catch `GlossaryValidationError`/`GlossaryConflictError` and exit 1 with the descriptive message.

### 2.1 — Aggregate

- **Command:** `.venv310\Scripts\python.exe -m pytest` (full suite)
- **Output:** `39 passed in 0.22s` — `test_glossary_normalize.py` (14), `test_glossary_scan.py` (9), `test_glossary_conflict.py` (4), `test_glossary_validation.py` (8), `test_glossary_sqlite.py` (4).
- **Aggregate import check:** `import src, src.glossary, src.exceptions` and all public symbols (`load_glossary_files`, `build_sqlite_index`, `load_glossary_index`, `normalize_arabic`, `normalize_english`, `scan_glossary_hits`, `glossary_scan`, `GlossaryIndex`, `Term`, `GlossaryHit`) → OK. No regression to `python -m src.cli doctor` (cli imports only `src.config`).
- **Note on Python version:** tests run on Python 3.10.11 because the host has no Python 3.11 (pyproject requires `>=3.11,<3.12`). `from __future__ import annotations` makes all PEP 604 union annotations evaluate as strings, so the module imports and runs cleanly on 3.10; on a real 3.11 host the behaviour is identical. `pytest` was installed into `.venv310` for this phase.

### 2.3.1 — Embedding adapter (embed_batch with nomic-embed-text)

- **Date:** 2026-07-02
- **Host:** Windows 10.0.26200; Python 3.10.11 (`.venv310`); Ollama 0.22.0 daemon running with `nomic-embed-text:latest` loaded.
- **Command:** `.venv310\Scripts\python.exe -c "from src.embeddings import embed_batch, EMBED_DIM; vecs = embed_batch([...32 strings...], batch_size=32); assert len(vecs)==32 and all(len(v)==EMBED_DIM for v in vecs)"`
- **Output:** `PASS: embedded 32 vectors, all dim 768` (16 English + 16 Arabic sample strings). First vector first 4 values: `[0.0094, -0.0052, -0.1406, -0.019]`.
- **Error-translation verify:** `Embedder(client=ollama.Client(host='http://localhost:9999'), model='nomic-embed-text', host='http://localhost:9999').embed('x')` → `EmbeddingConnectionError: cannot reach embedding engine at http://localhost:9999 (model=nomic-embed-text): ...` → PASS.
- **Verdict:** PASS. `src/embeddings.py` implements `embed_batch(texts, batch_size=32) -> list[list[float]]` via an `Embedder` adapter wrapping a single reused `ollama.Client` (clean-code §4.1: one httpx connection, not one per request). Bounded batches of 32 (offline-architecture §1.4). Engine exceptions translated to domain hierarchy per catch matrix (clean-code §3.2): `ConnectionError`/`OSError` → `EmbeddingConnectionError`, `TimeoutError`/timeout → `EmbeddingTimeoutError`, others → `EmbeddingError`. Each batch dimension-checked against `EMBED_DIM=768`. `EmbeddingAdapter` Protocol enables deterministic mock-based CI tests (testing-verification §3.2). `tests/test_embeddings.py`: 8 fast (mock + error translation) + 2 slow (real Ollama) — all fast pass.

### 2.3.2 — ChromaDB build + query

- **Date:** 2026-07-02
- **Host:** Windows 10.0.26200; Python 3.10.11 (`.venv310`); Ollama 0.22.0 daemon running.
- **Command:** `.venv310\Scripts\python.exe -c "from src.retrieval import build_chroma_collection, query_chroma; ..."` (50-chunk ingest + query in a tmp_path dir)
- **Output:**
  ```
  top1 chunk_id: civil_code_25_0 | article: 25 | dist: 0.2384
  PASS: ingested 50 chunks; top-1 is the correct article (civil_code_25_0)
  top8 ids: ['civil_code_25_0', 'civil_code_4_0', 'civil_code_34_0', ...]
  PASS: empty query returns []
  PASS: where filter restricts to article=25 -> ['civil_code_25_0']
  ```
- **Verdict:** PASS. `src/retrieval.py` implements `build_chroma_collection(chunks, persist_dir)` (atomic rebuild: temp dir → swap, offline-architecture §3.4; HNSW tuned: cosine/M=8/construction_ef=64, §3.2; batched adds of 64, §3.3) and `query_chroma(query_text, n_results=8, where=None)` (embeds via injected `EmbeddingAdapter`, `include=["documents","metadatas","distances"]` only, §3.5; `where` metadata filter; empty query → `[]`). Windows atomic-rebuild fix: telemetry disabled (`Settings(anonymized_telemetry=False)`) and `SharedSystemClient.clear_system_cache()` + `gc.collect()` before `rename` to release SQLite file handles. `tests/test_retrieval.py`: 8 fast (mock embedder, real ChromaDB in tmp_path) + 1 slow (real Ollama, 50 chunks) — all fast pass.

### 2.3.3 — Ingestion CLI (--rebuild / --glossary-only / --corpus-only / --limit)

- **Date:** 2026-07-02
- **Host:** Windows 10.0.26200; Python 3.10.11 (`.venv310`); Ollama 0.22.0 daemon running.
- **Commands:**
  - `.venv310\Scripts\python.exe -m src.ingestion --rebuild`
  - `.venv310\Scripts\python.exe -m src.cli doctor`
- **Output (ingestion):**
  ```
  [ingestion] Glossary: 3 files, 33 terms loaded, 0 conflicts, 0 validation errors.
  [ingestion] Corpus: 5 laws, 90 articles, 90 chunks, 0 parse errors.
  [ingestion] ChromaDB: collection 'iraqi_laws' rebuilt, 90 embeddings written.
  [ingestion] Duration: 4.5s. Manifest: ...data\ingestion_manifest.json (content_hash=74d4f38e22c3...).
  Ingestion complete (0 errors).
  ```
  Exit code: 0.
- **Output (doctor):**
  ```
  doctor: running environment checks
    [OK]   Ollama daemon reachable: connected, /api/tags responded
    [OK]   Required models present: qwen2.5:7b-instruct-q5_K_M + nomic-embed-text both installed
    [OK]   ChromaDB directory exists: ...\db\chroma
    [OK]   Glossary SQLite populated: ...\db\glossary.sqlite (2 tables)
    [OK]   RAM headroom estimate: total 31.7 GB; fixed budget 3.9 GB (LLM 0.9 GB, offload: 100% GPU); headroom ~27.8 GB
  All checks passed.
  ```
  Exit code: 0.
- **Real corpus created:** 8 files in `data/corpus/` (5 laws: civil_code ar+en, penal_code ar+en, civil_procedure_code ar+en, commercial_code ar, penal_procedure_code ar), 90 articles total. 3 glossary files in `data/glossary/` (civil_code, penal_code, civil_procedure_code), 33 terms total.
- **Verdict:** PASS. `src/ingestion.py` exposes a Typer `ingest_app` with the `ingest` command implementing all four flags. The command is an orchestrator (clean-code §2.1) delegating to `_ingest_glossary`, `_iter_corpus_chunks` (streaming, memory-bounded), and `build_chroma_collection` (atomic rebuild). Output matches DATA_SPEC §4 format. Non-zero error count exits 1. Chunk-id scheme: `{law_slug}_{lang}_{article}_{idx}` (language segment added to avoid bilingual-pair DuplicateIDError collisions). `tests/test_ingestion_pipeline.py` (7 tests) passes.

### 2.3.4 — Ingestion manifest (idempotent content hash)

- **Date:** 2026-07-02
- **Host:** Windows 10.0.26200; Python 3.10.11 (`.venv310`).
- **Command:** Two consecutive `.venv310\Scripts\python.exe -m src.ingestion --rebuild` runs; compare `content_hash` in `data/ingestion_manifest.json`.
- **Output:**
  ```
  First run content_hash:  74d4f38e22c3e80c37f3626d7c5f1c31053d57d40f1b5fd4c03b1f580340fbb6
  Second run content_hash: 74d4f38e22c3e80c37f3626d7c5f1c31053d57d40f1b5fd4c03b1f580340fbb6
  ```
  Manifest fields: version=1.0.0, 3 glossary files, 33 terms, 8 corpus files, 5 laws, 90 articles, 90 chunks, 90 embeddings, llm_model=qwen2.5:7b-instruct-q5_K_M, embed_model=nomic-embed-text.
- **Verdict:** PASS. `data/ingestion_manifest.json` is written by `_write_manifest` with: `version`, `timestamp` (ISO 8601 UTC), `content_hash` (deterministic SHA-256 over all file hashes + term/article/chunk counts + model versions — excludes timestamp so idempotency is verifiable), per-file `sha256`+`size`, glossary/corpus/chroma counts, model versions, duration. Two consecutive runs produced an identical `content_hash` → idempotent. `tests/test_ingestion_pipeline.py::TestManifestContentHash` + `TestManifestWriter` (7 tests) passes.

### Phase 2 Exit Criterion — Full corpus ingestion + semantic top-1 query

- **Date:** 2026-07-02
- **Commands:**
  - `.venv310\Scripts\python.exe -m src.ingestion --rebuild` → 0 errors, exit 0.
  - `.venv310\Scripts\python.exe -m src.cli doctor` → all 5 checks pass, exit 0.
  - Semantic query (EN): `query_chroma('contract of sale transfers ownership in exchange for a price')` → top-1 = `civil_code_en_5_0` (Article 5, the contract-of-sale article, dist 0.1494).
  - Semantic query (AR): `query_chroma('عقد البيع هو اتفاق يقتضي نقل ملكية...')` → top-1 = `civil_code_ar_5_0` (Article 5, Arabic).
  - Semantic query (penal): `query_chroma('penalty for theft committed at night with a weapon')` → top-1 = `penal_code_en_3_0` (the theft-penalty article).
  - Full test suite: `.venv310\Scripts\python.exe -m pytest tests/ -m "not slow"` → 88 passed, 3 deselected (slow real-Ollama tests), 0 failed.
- **Verdict:** PASS. `python -m src.ingestion --rebuild` completes with 0 errors on the full corpus + glossary (5 laws, 90 articles, 90 chunks, 33 glossary terms), and semantic queries in both EN and AR return the correct article as top-1. `python -m src.cli doctor` passes all checks.
