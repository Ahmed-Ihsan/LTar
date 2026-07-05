# Design Spec: SLM Alternatives for Low-RAM Operation of the Iraqi Legal Translation Agent

> **Status:** Draft (awaiting user review)
> **Date:** 2026-07-05
> **Methodology:** STORM (Stanford multi-perspective expert simulation → synthesized article)
> **Scope:** Alternatives to the current `qwen2.5:7b-instruct-q5_K_M` (~5.4 GB) engine so the agent runs reliably on the documented 8 GB RAM target. Two axes only: (A) model compression, (B) partial replacement with RAG / rules. Hybrid cloud-edge and alternative inference engines are out of scope for this spec (the latter is mentioned only as a complementary RAM optimization).

---

## 1. Problem Statement

The agent currently loads `qwen2.5:7b-instruct-q5_K_M` (~5.4 GB) via Ollama. On the documented 8 GB RAM target (Windows, CPU-only):

- OS + idle services consume ~2.5–3.5 GB.
- The loaded model consumes ~5.4 GB.
- Effective free RAM before the LLM call is ~1.6–2 GB.
- `RAMGuardError` fires at < 1.5 GB free (`src/memory.py::check_ram_guard`).
- Effective context is ≤ 4 K tokens despite `context_window: 8192` in `config.yaml`.
- Throughput is ~3–5 token/s on CPU; any task switch (browser, IDE) risks tripping the RAM guard.

**The device is not broken — it runs on the edge.** The goal is to **recover operating headroom and raise reliability**, not to fix a non-working setup. This widens the solution space.

**Untested assumption to invalidate first:** the implicit belief that "7B is the minimum for legal quality" has never been benchmarked against `3b-q8`, `3b-q5`, etc. on an Iraqi legal sample. No engineering decision should be made before that data exists.

## 2. Goals & Non-Goals

### Goals
1. Recover ≥ 2 GB of RAM headroom on the 8 GB target so the RAM guard never trips during normal operation.
2. Restore the full 8 K token context window.
3. Preserve legal-translation quality (no silent semantic drift, especially "softening" errors like "يُحكم" → "may be sentenced").
4. Stay within the project's architecture: adapter boundary, OCP for nodes, DI at the CLI seam, no engine exceptions leaking past adapters.

### Non-Goals
1. Cloud / hybrid cloud-edge offloading (explicitly excluded by the user).
2. Replacing Ollama entirely (llama.cpp server is mentioned only as a complementary RAM optimization, not a primary axis).
3. Changing the Translate → Audit → Revise loop topology or the `max_revisions: 3` cap.
4. Building a new corpus from scratch — the TM layer reuses `data/corpus` and the existing SQLite glossary.

## 3. The Two Axes (and Why They Are Synergistic, Not Alternatives)

| Scenario | RAM | Quality |
|----------|-----|---------|
| (A) compression only | freed | degraded |
| (B) RAG/TM only | unchanged | improved |
| **(A) + (B)** | **freed** | **preserved** |

(A) alone frees RAM but degrades quality. (B) alone improves quality but frees no RAM. **Together**, (B) compensates for (A)'s quality loss, and (A) lets (B) run on a weaker device. The synergy is **stronger in Iraqi legal Arabic** than in general text because legal drafting is highly formulaic (definitions, general provisions, penalty clauses) — a TM layer covers a large fraction of any new legal text, shrinking the LLM's working surface to syntax and connectives, which even a 3B model handles.

## 4. Axis A — Model Compression

### 4.1 Deeper Quantization of the Current 7B Model

| Variant | Size | Saving | General quality | Legal-Arabic verdict |
|---------|------|--------|-----------------|----------------------|
| `q5_K_M` (current) | 5.4 GB | — | safe | safe |
| `q4_K_M` | 4.4 GB | ~1 GB | safe | safe-ish |
| `q3_K_M` | 3.7 GB | ~1.7 GB | on the edge | **rejected** — softening errors |
| `q2_K` | 3.1 GB | ~2.3 GB | collapsed | rejected |

**Legal-specific concern:** legal text is especially sensitive to *Type II* errors (addition / softening of modal verbs), which light quantization tends to produce. "يُحكم بالسجن" vs "قد يُحكم بالسجن" changes a judicial outcome. `q3_K_M` is therefore **rejected for the Translator** in the legal context despite being acceptable in general benchmarks.

**Non-negotiable rule:** the **Auditor is never compressed**. It stays at `q5` or `q8`. The Translator can be compressed because the Auditor reviews it; the Auditor is reviewed by no one, so compressing it turns the system into "the blind leading the blind."

### 4.2 Moving to a Smaller Model (3B)

`qwen2.5:3b-instruct` at `q5` (~2.2 GB) frees ~3.2 GB — enough for the full 8 K context and effectively eliminating RAM-guard risk.

**Arabic floor:** models ≤ 1.5B produce broken Arabic because of low Arabic pretraining share. **The minimum acceptable for legal Arabic is 3B at q5 or better.** Below that we risk the syntactic structure itself, not just terminology.

**Legal floor:** a 3B model alone cannot distinguish fine legal terms. But it does not need to "know" the law — it needs to *transfer* given strong glossary + RAG context. This is exactly what Axis B provides.

### 4.3 Complementary Inference Optimizations (within compression scope)

Techniques that reduce RAM without changing the model:
- **KV cache quantization (q8 KV):** ~50% context-RAM reduction → enables 8 K context instead of 4 K on the same RAM budget.
- **mmap + mlock:** prevents swapping, stabilizes latency.
- **flash-attn on CPU:** ~20–30% KV cache reduction.

These are available via `llama.cpp` server directly. The project already has `llamacpp_url` in `config.yaml` and the `LLMEngineAdapter` protocol (`src/llm.py`) is extensible — adding a `LlamaCppEngineAdapter` respects OCP (new adapter, no node changes).

## 5. Axis B — Partial Replacement with RAG / Rules

### 5.1 Principle

Instead of asking the LLM to be a "legal expert that transfers", partition the work: **legal knowledge lives in the RAG/glossary layer; linguistic transfer lives in the LLM.** This shrinks the LLM's working surface to syntax and connectives — which a 3B model handles.

### 5.2 Three Replacement Layers

**Layer 1 — Glossary expanded into a Legal Translation Memory (TM)**
The existing SQLite glossary (`db/glossary.sqlite`) covers terms. Extension: add **legal sentence templates** (e.g. "يُعاقب بالسجن مدة لا تتجاوز..." → "shall be punished by imprisonment for a period not exceeding..."). This is a shift from a terminological glossary to an Iraqi legal TM. The SQLite schema is extensible; no new storage engine.

**Layer 2 — Sentence-level RAG**
Instead of retrieving long chunks, retrieve **aligned bilingual legal sentences** from the corpus. At similarity ≥ 98%, return the stored translation directly without invoking the LLM. This covers the repetitive parts of legal texts (definitions, penalty formulas) that make up a large fraction of any statute.

**Layer 3 — Post-translation rules**
Simple regex rules fix common mechanical errors (Unicode normalization, digit ordering, date formats). These reduce the Auditor's load.

### 5.3 Operational Cost

The TM/RAG/rules layer consumes **megabytes** (SQLite + a lightweight FAISS index < 200 MB), not gigabytes. **The impact-to-cost ratio here is the highest in the entire design** — far cheaper than any LLM RAM saving.

### 5.4 Safety Net

- **High similarity threshold (≥ 98%)** for accepting TM output. Anything lower goes to the LLM. Better slow than silently wrong.
- **Conservative decision classifier** determines: "repetitive" sentence (→ TM) vs "novel" sentence (→ LLM). Can be a simple similarity rule, no LLM needed.
- **The Auditor does not review TM outputs** because they are "pre-approved" — therefore the threshold must be strict.

## 6. Interaction with the Existing Architecture

The design respects every constraint in `AGENTS.md` and the `.devin/skills/*`:

- **Adapter boundary:** any new engine (llama.cpp, a 3B model loader) is wrapped in an adapter implementing `LLMEngineAdapter`. Engine exceptions are translated to domain exceptions inside the adapter. Nodes and CLI never see engine types.
- **DI / CLI seam:** concrete adapters are constructed in `src/cli.py`. `run_translation` / `run_translation_streamed` remain the orchestration seams; tests inject mocks — no Ollama, no network in CI.
- **OCP:** node functions in `src/nodes.py` are closed for modification. The TM layer is a new pre-processing stage, not a modification of the Translator node. The decision classifier is a new component, not a change to existing nodes.
- **Single source of truth:** `src/memory.py` still owns RAM reading; the RAM guard stays as-is.
- **Config:** new keys added to `AppConfig` (`config.py`) with Pydantic validation — e.g. `translator_model`, `auditor_model` (to allow different models per node), `tm_similarity_threshold`, `tm_enabled`.

### 6.1 New Config Keys (proposed)

```yaml
# Per-node model selection (enables 3B translator + 7B auditor)
translator_model: qwen2.5:3b-instruct-q5_K_M
auditor_model: qwen2.5:7b-instruct-q5_K_M   # never compressed

# TM / sentence-level RAG
tm_enabled: true
tm_similarity_threshold: 0.98
tm_db: db/tm.sqlite                          # extends glossary schema
```

### 6.2 New Components

1. `src/tm.py` — `TranslationMemory` class: sentence alignment, similarity search, threshold-gated retrieval. Reuses the `GlossaryAdapter` SQLite pattern.
2. `src/decision.py` — `RouteDecision`: decides TM vs LLM per sentence. Pure function, deterministic, no LLM.
3. `LlamaCppEngineAdapter` (in `src/llm.py`) — optional, for the KV-cache-quantization path. Same protocol, new concrete class.
4. New pre-processing node `tm_lookup` in `src/graph.py` (added, not modifying existing nodes — OCP).

## 7. Safety Rules (Non-Negotiable)

1. **The Auditor is never compressed.** It stays at `q5` or `q8` regardless of what the Translator uses.
2. **TM acceptance threshold ≥ 98% similarity.** Anything lower goes to the LLM.
3. **TM outputs bypass the Auditor** (pre-approved) — therefore the threshold is strict and the TM corpus is curated.
4. **No engine exception type escapes an adapter.** New adapters must translate to the existing `LLMRuntimeError` hierarchy in `src/exceptions.py`.
5. **RAM guard stays in place.** Compression is not a reason to remove the guard; it is a reason the guard fires less often.

## 8. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| TM returns a 90%-similar sentence with a critical legal difference → silent error | High | ≥ 98% threshold + conservative classifier; TM corpus is human-curated |
| Compressed Auditor approves a subtle semantic error | High | Auditor never compressed (rule §7.1) |
| Model swap (load/unload) latency on HDD | Medium | Prefer single-model-per-role; use mmap+mlock; document SSD requirement |
| Operational complexity: each new layer adds failure points | Medium | Each layer is opt-in via config (`tm_enabled`, etc.); defaults preserve current behavior |
| 3B Arabic quality unverified | High | **Benchmark before adoption** (recommendation §9.1) |
| TM corpus construction effort | Medium | Reuse `data/corpus` + existing glossary; sentence alignment is one-time work |

## 9. Ordered Recommendations

1. **Benchmark before any change.** Compare `7b-q5`, `3b-q8`, `3b-q5` on an Iraqi legal sample with the Auditor active. No engineering decision before data. This is the single most important step — the "7B floor" assumption is untested.
2. **Lowest-risk first step:** switch to `qwen2.5:7b-q4_K_M` (~1 GB saving, quality safe-ish). No code change — just `config.yaml`.
3. **Structural step:** build the legal TM layer on the existing SQLite glossary + sentence alignment from `data/corpus`. One-time work, pays off on every future run.
4. **Integration step:** after (1) validates quality, move the Translator to `3b-q5` while keeping the Auditor on `7b-q5`. Requires per-node model config + an adapter that can load two models (or swap with mmap).
5. **Performance step:** add a `LlamaCppEngineAdapter` with KV cache quantization to restore the full 8 K context.
6. **Non-negotiable:** Auditor never compressed; TM threshold ≥ 98%.

## 10. Verification Plan

Per `testing-verification` skill — no Ollama daemon, no network in CI:

- **Unit tests** for `TranslationMemory` (similarity, threshold gating, miss → fallback).
- **Unit tests** for `RouteDecision` (deterministic routing, edge cases at the threshold).
- **Adapter tests** for `LlamaCppEngineAdapter` with a mock HTTP client (same pattern as the existing Ollama adapter tests).
- **Integration test** for the new `tm_lookup` node using an in-memory TM (no real SQLite file).
- **Quality benchmark** (manual, out of CI): run the sample in `legal_input_ar.txt` through `7b-q5`, `3b-q8`, `3b-q5` and compare against `legal_output_en.txt` / `legal_output_ar.txt` with the Auditor's verdict matrix.
- **RAM profile** (manual): measure peak RSS for each config on the 8 GB target; confirm the RAM guard does not fire during a full translate→audit→revise loop.

## 11. Open Questions (to resolve during planning)

1. Does `data/corpus` contain enough bilingual aligned sentences to seed a useful TM, or do we need to align ar/en pairs first? (Quick check needed before sizing step 3.)
2. Should the TM store exact sentence pairs only, or also sub-sentence templates (clause fragments)?
3. Is the `3b-q5` Translator + `7b-q5` Auditor path acceptable given the model-swap latency, or do we require a single loaded model that plays both roles?
4. Should `LlamaCppEngineAdapter` be in this spec's scope or a follow-up spec? (Current scope: mentioned, not specified in detail.)

---

## Appendix — Expert Panel (STORM Stage 1)

| # | Expert | Bias they defend |
|---|--------|------------------|
| 1 | Dr. Layla Al-Obaidi — Iraqi legal translation | Legal accuracy above all; rejects any solution that weakens terminological fidelity |
| 2 | Karim Al-Hasan — Edge inference (llama.cpp / GGUF) | Deep quantization + alternative engines to Ollama |
| 3 | Dr. Sarah Al-Mutairi — model compression research | Pruning and distillation as radical size reduction |
| 4 | Omar Al-Farouk — low-resource systems engineering | RAM budget, swap, offloading, operational realism |
| 5 | Dr. Noura Al-Ibrahim — RAG & legal retrieval | Strengthen glossary/RAG to reduce the LLM's burden in the first place |
| 6 | Hassan Al-Tamimi — Arabic NLP | Challenges of Arabic in very small (1B–3B) models |

The full simulated conversation (Stage 2) is preserved in the chat transcript; this spec is the Stage 3 synthesis.
