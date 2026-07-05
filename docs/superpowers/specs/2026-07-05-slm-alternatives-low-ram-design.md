# Design Spec: SLM Alternatives for Low-RAM Operation of the Iraqi Legal Translation Agent

> **Status:** Draft (awaiting user review)
> **Date:** 2026-07-05
> **Methodology:** STORM (Stanford multi-perspective expert simulation → synthesized article)
> **Scope:** Replace the current `qwen2.5:7b-instruct-q5_K_M` (~5.4 GB) engine with **Gemma 3 4B** (~3.3 GB) so the agent runs reliably on the documented 8 GB RAM target. Two axes: (A) model replacement + compression, (B) partial replacement with RAG / rules. Hybrid cloud-edge is out of scope. llama.cpp is mentioned only as a complementary optimization.

---

## 1. Problem Statement

The agent currently loads `qwen2.5:7b-instruct-q5_K_M` (~5.4 GB) via Ollama. On the documented 8 GB RAM target (Windows, CPU-only):

- OS + idle services consume ~2.5–3.5 GB.
- The loaded model consumes ~5.4 GB.
- Effective free RAM before the LLM call is ~1.6–2 GB.
- `RAMGuardError` fires at < 1.5 GB free (`src/memory.py::check_ram_guard`).
- Effective context is ≤ 4 K tokens despite `context_window: 8192` in `config.yaml`.
- Throughput is ~3–5 token/s on CPU; any task switch (browser, IDE) risks tripping the RAM guard.

**The device is not broken — it runs on the edge.** The goal is to **recover operating headroom and raise reliability**, not to fix a non-working setup.

**Chosen replacement:** Google's **Gemma 3 4B** (`gemma3:4b` on Ollama, Q4_K_M, ~3.3 GB, 128K context window). This frees ~2.1 GB of RAM — enough to restore the full 8 K context and eliminate RAM-guard risk during normal operation. Gemma 3 (released 2025) has strong multilingual capabilities including Arabic, and is available on Ollama with no code changes required (just `config.yaml`).

**Untested assumption to invalidate first:** the implicit belief that "7B is the minimum for legal quality" has never been benchmarked against Gemma 3 4B on an Iraqi legal sample. No engineering decision should be made before that data exists.

## 2. Goals & Non-Goals

### Goals
1. Recover ≥ 2 GB of RAM headroom on the 8 GB target so the RAM guard never trips during normal operation.
2. Restore the full 8 K token context window (Gemma 3 supports 128K natively).
3. Preserve legal-translation quality (no silent semantic drift, especially "softening" errors like "يُحكم" → "may be sentenced").
4. Stay within the project's architecture: adapter boundary, OCP for nodes, DI at the CLI seam, no engine exceptions leaking past adapters.

### Non-Goals
1. Cloud / hybrid cloud-edge offloading (explicitly excluded by the user).
2. Replacing Ollama entirely (llama.cpp server is mentioned only as a complementary RAM optimization, not a primary axis).
3. Changing the Translate → Audit → Revise loop topology or the `max_revisions: 3` cap.
4. Building a new corpus from scratch — the TM layer reuses `data/corpus` and the existing SQLite glossary.
5. Using TranslateGemma 4B (evaluated and rejected — see §4.4).

## 3. The Two Axes (and Why They Are Synergistic, Not Alternatives)

| Scenario | RAM | Quality |
|----------|-----|---------|
| (A) Gemma 3 4B only | freed (~2.1 GB) | potentially degraded (4B vs 7B) |
| (B) RAG/TM only | unchanged | improved |
| **(A) + (B)** | **freed** | **preserved** |

(A) alone frees RAM but may degrade quality (4B vs 7B). (B) alone improves quality but frees no RAM. **Together**, (B) compensates for (A)'s quality loss, and (A) lets (B) run on a weaker device. The synergy is **stronger in Iraqi legal Arabic** than in general text because legal drafting is highly formulaic (definitions, general provisions, penalty clauses) — a TM layer covers a large fraction of any new legal text, shrinking the LLM's working surface to syntax and connectives, which a 4B model handles.

## 4. Axis A — Model Replacement: Qwen 2.5 7B → Gemma 3 4B

### 4.1 Why Gemma 3 4B

| Property | Qwen 2.5 7B (current) | Gemma 3 4B (chosen) |
|----------|----------------------|---------------------|
| Ollama tag | `qwen2.5:7b-instruct-q5_K_M` | `gemma3:4b` |
| Size (loaded) | ~5.4 GB | ~3.3 GB (Q4_K_M) |
| RAM saving | — | ~2.1 GB |
| Context window | 8 K (effective ≤ 4 K on 8 GB) | 128 K (effective 8 K+ on 8 GB) |
| Multilingual / Arabic | strong | strong (Google's multilingual training) |
| Release year | 2024 | 2025 |
| Ollama availability | yes | yes (`ollama pull gemma3:4b`) |
| Code changes needed | — | **none** (just `config.yaml`) |

Gemma 3 4B is available on Ollama as `gemma3:4b` (Q4_K_M, 3.3 GB, 36.8M downloads). The switch requires only changing `llm_model` in `config.yaml` — no adapter changes, no new code. The 128K context window means the 8 K configured context is trivially supported.

### 4.2 Quantization Options for Gemma 3 4B

If further RAM savings are needed, Gemma 3 4B has deeper quantization variants (via HuggingFace GGUF, not all on Ollama):

| Variant | Size | Saving vs current | Quality | Source |
|---------|------|-------------------|---------|--------|
| `Q4_K_M` (Ollama default) | 3.3 GB | ~2.1 GB | recommended balance | Ollama `gemma3:4b` |
| `Q5_K_M` | 2.9 GB | ~2.5 GB | near-lossless | HuggingFace GGUF |
| `Q8_0` | 4.2 GB | ~1.2 GB | virtually lossless | HuggingFace GGUF |
| Google QAT `Q4_0` | 3.16 GB | ~2.2 GB | "preserves BF16 quality" (Google's claim) | `google/gemma-3-4b-it-qat-q4_0-gguf` |

**Recommendation:** start with Ollama's `gemma3:4b` (Q4_K_M, 3.3 GB) — simplest path, no adapter changes. If quality is insufficient, try QAT Q4_0 (Google's quantization-aware training, claimed to preserve BF16 quality).

### 4.3 Both Nodes Use Gemma 3 4B (User Decision)

The user has decided: **both Translator and Auditor use `gemma3:4b`**. This replaces Qwen 2.5 7B entirely.

**This conflicts with the original STORM panel's recommendation** that "the Auditor is never compressed." The original rule assumed same-family quantization (7B q5 vs 7B q3). Here we're changing the model family entirely — Gemma 3 (2025) may outperform Qwen 2.5 (2024) in reasoning despite being smaller, but this is **unverified**.

**Risk acceptance (user decision):** the user accepts the 4B Auditor risk. The benchmark (§9.1) will verify whether Gemma 3 4B's Auditor verdicts match or exceed Qwen 2.5 7B's on the Iraqi legal sample. If the benchmark shows the Auditor approving subtle semantic errors, the fallback is to use a larger Gemma variant (12B) for the Auditor only — but this requires the two-model swap path (§11, open question).

**Revised safety rule:** the Auditor uses the **best available quantization** of Gemma 3 4B (Q8_0 if RAM allows, Q4_K_M as floor). The Auditor is never given a *deeper* quantization than the Translator.

### 4.4 TranslateGemma 4B — Evaluated and Rejected

Google's **TranslateGemma 4B** is a translation-specialized fine-tune of Gemma 3 4B. It outperforms baseline Gemma 3 on WMT24++ across 55 language pairs (including Arabic). However, it was **rejected** for this project because:

1. **2K token context limit for translation quality** — the current pipeline sends system prompt + glossary hits + RAG chunks + input text, which easily exceeds 2K. Quality degrades beyond 2K per Google's own documentation.
2. **Not on Ollama** — only available as GGUF on HuggingFace, requiring a llama.cpp adapter (more engineering work).
3. **Weaker at non-translation tasks** — "may struggle with non-translation tasks" per the technical report. The Auditor node needs reasoning/critique, not translation. TranslateGemma would be worse for the Auditor role.
4. **No per-node model split** — the user chose a single model for both nodes, which favors the general-purpose Gemma 3 4B.

### 4.5 Complementary Inference Optimizations

Techniques that reduce RAM without changing the model (optional, via llama.cpp):
- **KV cache quantization (q8 KV):** ~50% context-RAM reduction → enables even larger context.
- **mmap + mlock:** prevents swapping, stabilizes latency.
- **flash-attn on CPU:** ~20–30% KV cache reduction.

These are available via `llama.cpp` server. The project has `llamacpp_url` in `config.yaml` and the `LLMEngineAdapter` protocol is extensible — adding a `LlamaCppEngineAdapter` respects OCP. This is a follow-up optimization, not part of the initial Gemma 3 4B switch.

## 5. Axis B — Partial Replacement with RAG / Rules

### 5.1 Principle

Instead of asking the LLM to be a "legal expert that transfers", partition the work: **legal knowledge lives in the RAG/glossary layer; linguistic transfer lives in the LLM.** This shrinks the LLM's working surface to syntax and connectives — which a 4B model handles. This axis becomes **more critical** with the 4B choice: the smaller model needs more help with legal terminology.

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

- **Adapter boundary:** the existing `OllamaEngineAdapter` works with Gemma 3 4B unchanged — it's just a different model name passed to `ollama.Client.chat`. No new adapter needed for the initial switch. A `LlamaCppEngineAdapter` (optional, follow-up) would implement the same `LLMEngineAdapter` protocol.
- **DI / CLI seam:** concrete adapters are constructed in `src/cli.py`. `run_translation` / `run_translation_streamed` remain the orchestration seams; tests inject mocks — no Ollama, no network in CI.
- **OCP:** node functions in `src/nodes.py` are closed for modification. The TM layer is a new pre-processing stage, not a modification of the Translator node. The decision classifier is a new component, not a change to existing nodes.
- **Single source of truth:** `src/memory.py` still owns RAM reading; the RAM guard stays as-is.
- **Config:** `llm_model` changes to `gemma3:4b`. New keys added for TM features.

### 6.1 Config Changes (proposed)

```yaml
# Model switch — both nodes use Gemma 3 4B
llm_model: gemma3:4b              # was qwen2.5:7b-instruct-q5_K_M

# TM / sentence-level RAG (new)
tm_enabled: true
tm_similarity_threshold: 0.98
tm_db: db/tm.sqlite               # extends glossary schema
```

### 6.2 New Components

1. `src/tm.py` — `TranslationMemory` class: sentence alignment, similarity search, threshold-gated retrieval. Reuses the `GlossaryAdapter` SQLite pattern.
2. `src/decision.py` — `RouteDecision`: decides TM vs LLM per sentence. Pure function, deterministic, no LLM.
3. `LlamaCppEngineAdapter` (in `src/llm.py`) — optional follow-up, for the KV-cache-quantization path. Same protocol, new concrete class.
4. New pre-processing node `tm_lookup` in `src/graph.py` (added, not modifying existing nodes — OCP).

## 7. Safety Rules

1. **The Auditor uses the best available quantization** of the chosen model. If both nodes use `gemma3:4b` (Q4_K_M), the Auditor must not be given a deeper quantization than the Translator. If RAM allows, the Auditor should use Q8_0.
2. **TM acceptance threshold ≥ 98% similarity.** Anything lower goes to the LLM.
3. **TM outputs bypass the Auditor** (pre-approved) — therefore the threshold is strict and the TM corpus is curated.
4. **No engine exception type escapes an adapter.** New adapters must translate to the existing `LLMRuntimeError` hierarchy in `src/exceptions.py`.
5. **RAM guard stays in place.** The model switch is not a reason to remove the guard; it is a reason the guard fires less often.
6. **Benchmark before permanent adoption.** If Gemma 3 4B's Auditor verdicts show quality regression vs Qwen 2.5 7B on the legal sample, the fallback is a larger Auditor model (Gemma 3 12B or revert to Qwen 7B for Auditor only).

## 8. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| 4B Auditor approves subtle semantic errors that 7B would catch | **High** | Benchmark before permanent adoption (§9.1); fallback to larger Auditor model if regression detected |
| TM returns a 90%-similar sentence with a critical legal difference → silent error | High | ≥ 98% threshold + conservative classifier; TM corpus is human-curated |
| Gemma 3 4B Arabic legal quality unverified | High | **Benchmark before adoption** (recommendation §9.1) |
| Operational complexity: each new layer adds failure points | Medium | Each layer is opt-in via config (`tm_enabled`, etc.); defaults preserve current behavior |
| TM corpus construction effort | Medium | Reuse `data/corpus` + existing glossary; sentence alignment is one-time work |
| Gemma 3 4B multimodal overhead (vision encoder) | Low | Ollama's `gemma3:4b` includes the vision component but it's not loaded for text-only inference; verify with RAM profiling |

## 9. Ordered Recommendations

1. **Benchmark before any change.** Compare Qwen 2.5 7B (current) vs Gemma 3 4B on an Iraqi legal sample (`legal_input_ar.txt` → `legal_output_en.txt`) with the Auditor active. Specifically verify: (a) Translator quality, (b) Auditor verdict accuracy (does 4B Auditor catch the same errors as 7B?). No permanent switch before this data.
2. **Lowest-risk first step:** switch `llm_model` to `gemma3:4b` in `config.yaml`. No code change. Pull with `ollama pull gemma3:4b`. Run the existing test suite (mock-based, no daemon needed) to confirm no breakage.
3. **Structural step:** build the legal TM layer on the existing SQLite glossary + sentence alignment from `data/corpus`. One-time work, pays off on every future run.
4. **Integration step:** add the `tm_lookup` pre-processing node + `RouteDecision` classifier to the graph. Opt-in via `tm_enabled` config flag.
5. **Performance step (optional follow-up):** add a `LlamaCppEngineAdapter` with KV cache quantization for even larger context / faster inference.
6. **Fallback plan:** if the benchmark (step 1) shows Auditor quality regression, use Gemma 3 12B (`gemma3:12b`, 8.1 GB) or Qwen 2.5 7B for the Auditor only — requires per-node model config (`translator_model` / `auditor_model` split).

## 10. Verification Plan

Per `testing-verification` skill — no Ollama daemon, no network in CI:

- **Existing test suite:** `.\.venv310\Scripts\python.exe -m pytest tests/ -q` must still pass (~192 tests). The model name change in config does not affect mock-based tests.
- **Unit tests** for `TranslationMemory` (similarity, threshold gating, miss → fallback).
- **Unit tests** for `RouteDecision` (deterministic routing, edge cases at the threshold).
- **Integration test** for the new `tm_lookup` node using an in-memory TM (no real SQLite file).
- **Quality benchmark** (manual, out of CI): run `legal_input_ar.txt` through Qwen 7B and Gemma 3 4B, compare against `legal_output_en.txt` with the Auditor's verdict matrix. Key metric: does the 4B Auditor catch the same errors as the 7B Auditor?
- **RAM profile** (manual): measure peak RSS for `gemma3:4b` on the 8 GB target; confirm the RAM guard does not fire during a full translate→audit→revise loop. Expected: ~3.3 GB model + ~3 GB OS = ~6.3 GB used, ~1.7 GB free — above the 1.5 GB guard.
- **Lint:** `.\.venv310\Scripts\python.exe -m ruff check <changed files>` (only changed files per AGENTS.md).

## 11. Open Questions (to resolve during planning)

1. Does `data/corpus` contain enough bilingual aligned sentences to seed a useful TM, or do we need to align ar/en pairs first? (Quick check needed before sizing step 3.)
2. Should the TM store exact sentence pairs only, or also sub-sentence templates (clause fragments)?
3. If the benchmark shows 4B Auditor quality regression: do we fall back to Gemma 3 12B for Auditor (requires per-node model config + swap logic), or revert to Qwen 7B for Auditor only?
4. Should `LlamaCppEngineAdapter` be in this spec's scope or a follow-up spec? (Current scope: mentioned, not specified in detail.)
5. Does Ollama's `gemma3:4b` load the vision encoder overhead for text-only inference? (Verify with RAM profiling in step 2.)

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

## Appendix B — Model Research Summary

### Gemma 3 4B (chosen)
- Ollama: `gemma3:4b` — Q4_K_M, 3.3 GB, 128K context, 36.8M downloads
- HuggingFace GGUF variants: Q5_K_M (2.9 GB), Q8_0 (4.2 GB), QAT Q4_0 (3.16 GB)
- Google QAT claim: "preserves similar quality as bfloat16 while using 3x less memory"
- Multilingual with strong Arabic support

### TranslateGemma 4B (evaluated, rejected)
- Translation-specialized fine-tune of Gemma 3 4B
- Outperforms baseline Gemma 3 on WMT24++ (55 languages including Arabic)
- **Rejected because:** 2K context limit for translation quality (project needs 8K+), not on Ollama, weaker at non-translation tasks (Auditor needs reasoning)
- Available as GGUF on HuggingFace (`mradermacher/translategemma-4b-it-GGUF`)

### Gemma 3 12B (fallback for Auditor)
- Ollama: `gemma3:12b` — 8.1 GB (too big for 8 GB RAM as-is, would need q3 ~5 GB)
- Fallback option if 4B Auditor quality is insufficient
