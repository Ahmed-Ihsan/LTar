# Architecture

> Engineering blueprint for the Iraqi Legal Translation Agent. Defines the end-to-end pipeline, data stores, and LangGraph state machine that governs the Translate → Audit → Revise loop.

---

## 1. System Overview

The system is a single-process, offline Python application. All inference is local via Ollama. The pipeline is a directed graph with deterministic pre/post-processing stages wrapped around two LLM-driven agent nodes.

```
┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌───────────────┐    ┌──────────────┐    ┌──────────────┐
│ Input Text  │ -> │ Exact-Match      │ -> │ ChromaDB RAG    │ -> │ Translator    │ -> │ Auditor      │ -> │ Final Output │
│ (AR or EN)  │    │ Glossary Lookup  │    │ Context Retrieval│   │ Agent         │    │ Agent        │    │              │
└─────────────┘    └────────┬─────────┘    └────────┬────────┘    └──────┬───────┘    └──────┬───────┘    └──────────────┘
                            │                       │                    │                  │
                   ┌────────▼───────────────────────▼────────────────────▼──────────────────▼────────┐
                   │                        ADAPTER LAYER (uniform interfaces)                        │
                   │  GlossaryAdapter  RetrievalAdapter  TranslatorAdapter  AuditorAdapter           │
                   │       │                │                  │                     │               │
                   │  ┌────▼────┐     ┌─────▼─────┐     ┌──────▼──────┐      ┌───────▼───────┐       │
                   │  │ SQLite  │     │ ChromaDB  │     │ LLM Engine  │      │ LLM Engine    │       │
                   │  │ Engine  │     │ Engine    │     │ Adapter     │      │ Adapter       │       │
                   │  └─────────┘     └───────────┘     │ (Ollama/    │      │ (Ollama/      │       │
                   │                                    │  LlamaCpp/  │      │  LlamaCpp/    │       │
                   │                                    │  Mock)      │      │  Mock)        │       │
                   │                                    └─────────────┘      └───────────────┘       │
                   └─────────────────────────────────────────────────────────────────────────────────┘
                                                                  ^          │
                                                                  │          │ (revise)
                                                                  └──────────┘
                                                                       (loop, max 3)
```

The **Adapter Layer** sits between the LangGraph nodes and all concrete engines (SQLite, ChromaDB, Ollama). Each pipeline stage talks to its engine through a uniform adapter interface, never directly. This allows swapping any engine (e.g., Ollama → LlamaCpp, SQLite → DuckDB) without modifying node or graph code. See §5 for the full adapter specification.

### Stage Responsibilities

1. **Input Text** — Raw legal clause, single article, or short paragraph. Direction flag (`ar-en` or `en-ar`) supplied by caller.
2. **Exact-Match Glossary Lookup** — Token/phrase scan of the input against the SQLite glossary index. Hits are extracted as `glossary_hits` and removed from the LLM's translation burden by being pre-bound to their canonical target.
3. **ChromaDB RAG** — Semantic retrieval of the top-k most relevant chunks from the Iraqi laws corpus. Provides statutory context to ground the translator.
4. **Translator Agent** — Produces a draft translation conditioned on glossary hits + retrieved context + system prompt.
5. **Auditor Agent** — Reviews the draft against glossary compliance, legal fidelity, and fluency. Either `APPROVE` (terminate) or `REVISE` (return to Translator with a structured critique).
6. **Final Output** — Approved translation plus provenance metadata (glossary terms applied, source chunks cited, audit verdict).

---

## 2. Pipeline Flow (Detailed)

### 2.1 Pre-Processing (Deterministic, No LLM)

```
input_text
  │
  ├─> normalize_unicode()        # NFC, strip tatweel, normalize Arabic diacritics option
  ├─> segment_sentences()        # language-aware splitter
  ├─> glossary_scan()            # longest-match against SQLite glossary
  │       └─> glossary_hits: List[{source_term, target_term, law_ref, note}]
  └─> detect_direction()         # ar-en or en-ar (overridable by caller)
```

The glossary scan uses **longest-match-first** ordering so multi-word terms (e.g., "عقد البيع" → "contract of sale") win over single-word sub-matches. Hits are recorded with their character offsets so the translator prompt can reference them precisely.

### 2.2 Retrieval (ChromaDB)

```
embedding = ollama.embed(input_text, model="nomic-embed-text")
results = chroma.query(
    query_embeddings=[embedding],
    n_results=8,
    where={"law": {"$in": relevant_laws}},   # optional filter
)
context_chunks = results[:8]   # cap at 8 to respect token budget
```

Retrieval is performed on the **source-language** side of the corpus. The corpus is stored bilingually where available; when only Arabic source exists, the translator is instructed to translate from Arabic with English context only as a secondary signal.

### 2.3 Translator Agent Node

Inputs to the prompt:
- System role rules (see `PROMPTS.md`).
- `glossary_hits` — formatted as a numbered list of `source → target` bindings.
- `context_chunks` — formatted with `[Chunk k | Law: <name> | Article: <n>]` headers.
- `input_text` — the normalized source.
- `direction` — explicit instruction.

Output: a single draft translation string, plus an inline list of glossary terms it applied (for the auditor to verify).

### 2.4 Auditor Agent Node

Inputs:
- The original source text.
- The draft translation.
- The `glossary_hits` (ground truth bindings).
- A checklist rubric (see `PROMPTS.md`).

Output: a structured verdict:
```json
{
  "verdict": "APPROVE" | "REVISE",
  "critique": "string",
  "violations": ["string", ...],
  "confidence": 0.0-1.0
}
```

### 2.5 Edge Routing

```
if auditor.verdict == "APPROVE":
    -> END
elif auditor.verdict == "REVISE" and revision_count < 3:
    -> Translator (with critique injected into state)
else:
    -> END (emit best-effort draft + warning flag)
```

The **max revision count is 3**. This is a hard bound to prevent infinite loops and to cap latency on an 8 GB machine where each LLM call is the dominant cost.

---

## 3. Data Stores

### 3.1 SQLite Glossary Index (`db/glossary.sqlite`)

A read-optimized index built from `data/glossary/*.json` at ingestion time.

```sql
CREATE TABLE glossary (
    id            INTEGER PRIMARY KEY,
    source_term   TEXT NOT NULL,          -- normalized, lowercase for EN / diacritic-stripped for AR
    source_lang   TEXT NOT NULL,          -- 'ar' | 'en'
    target_term   TEXT NOT NULL,
    target_lang   TEXT NOT NULL,
    law_ref       TEXT,                   -- e.g. 'Civil Code', 'Penal Code'
    article_ref   TEXT,                   -- e.g. '148'
    note          TEXT,                   -- usage guidance
    priority      INTEGER DEFAULT 0,      -- higher wins on conflict
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_source_term ON glossary(source_term);
CREATE INDEX idx_source_lang ON glossary(source_lang);
```

**Lookup algorithm**: longest-match-first. All candidate terms whose `source_term` is a substring of the input are collected, then sorted by `len(source_term) DESC, priority DESC`. Overlapping shorter matches that fall within a longer match's span are discarded.

### 3.2 ChromaDB Vector Index (`db/chroma/`)

Persistent local collection. Single collection `iraqi_laws`.

| Field | Type | Description |
|---|---|---|
| `id` | string | `{law}_{article}_{chunk_idx}` |
| `embedding` | float[768] | `nomic-embed-text` |
| `document` | string | The chunk text (source language) |
| `metadata.law` | string | `Civil Code`, `Penal Code`, etc. |
| `metadata.article` | string | Article number or range |
| `metadata.lang` | string | `ar` or `en` |
| `metadata.chunk_idx` | int | Index within the article |
| `metadata.char_start` | int | Start offset in source file |
| `metadata.char_end` | int | End offset in source file |

Distance metric: **cosine** (default for `nomic-embed-text`).

### 3.3 Glossary JSON Source (`data/glossary/*.json`)

Human-editable source of truth. See `DATA_SPEC.md` for the full schema. Each file maps to a law domain. The SQLite index is a derived artifact and is rebuilt from these files.

---

## 4. LangGraph State Management

### 4.1 State Schema (`src/state.py`)

```python
from typing import TypedDict, List, Optional, Literal

class GlossaryHit(TypedDict):
    source_term: str
    target_term: str
    law_ref: str
    article_ref: str
    note: str
    char_start: int
    char_end: int

class ContextChunk(TypedDict):
    text: str
    law: str
    article: str
    score: float

class AuditVerdict(TypedDict):
    verdict: Literal["APPROVE", "REVISE"]
    critique: str
    violations: List[str]
    confidence: float

class TranslationState(TypedDict):
    input_text: str
    direction: Literal["ar-en", "en-ar"]
    glossary_hits: List[GlossaryHit]
    context_chunks: List[ContextChunk]
    draft: str
    audit: Optional[AuditVerdict]
    revision_count: int
    final_output: Optional[str]
    warnings: List[str]
```

### 4.2 Graph Definition (`src/graph.py`)

```python
from langgraph.graph import StateGraph, END

graph = StateGraph(TranslationState)

graph.add_node("preprocess", preprocess_node)     # glossary scan + retrieval
graph.add_node("translate", translate_node)        # translator agent
graph.add_node("audit", audit_node)                # auditor agent
graph.add_node("finalize", finalize_node)          # emit output

graph.set_entry_point("preprocess")
graph.add_edge("preprocess", "translate")
graph.add_edge("translate", "audit")

def route_audit(state: TranslationState) -> str:
    if state["audit"]["verdict"] == "APPROVE":
        return "finalize"
    if state["revision_count"] >= 3:
        state["warnings"].append("Max revisions reached; emitting best-effort draft.")
        return "finalize"
    return "translate"

graph.add_conditional_edges("audit", route_audit, {
    "finalize": "finalize",
    "translate": "translate",
})
graph.add_edge("finalize", END)

app = graph.compile()
```

### 4.3 Edge Routing Criteria

| From | To | Condition |
|---|---|---|
| `START` | `preprocess` | Always |
| `preprocess` | `translate` | Always |
| `translate` | `audit` | Always |
| `audit` | `finalize` | `verdict == APPROVE` OR `revision_count >= 3` |
| `audit` | `translate` | `verdict == REVISE` AND `revision_count < 3` |
| `finalize` | `END` | Always |

### 4.4 State Mutation Rules

- `preprocess` is the **only** node that writes `glossary_hits` and `context_chunks`.
- `translate` reads `glossary_hits`, `context_chunks`, `direction`, `input_text`; writes `draft` and increments `revision_count` only on re-entry (not on first pass — first pass sets `revision_count = 0`).
- `audit` reads `draft`, `glossary_hits`, `input_text`; writes `audit`.
- `finalize` reads `draft`, `audit`; writes `final_output` and appends to `warnings` if applicable.
- No node may mutate fields it does not own. This is enforced by unit tests.

---

## 5. Adapter Layer

The Adapter Layer is the structural boundary that decouples LangGraph orchestration from all concrete engines. Every pipeline stage interacts with its engine exclusively through an adapter that implements a uniform protocol. No node, no graph code, and no CLI code ever imports a concrete engine (`sqlite3`, `chromadb`, `ollama`) directly — they import adapter protocols.

### 5.1 Design Rationale

Without adapters, the LangGraph nodes are permanently welded to specific engines. Swapping Ollama for `llama.cpp`, or ChromaDB for DuckDB, requires editing every node. With adapters:

- **Engine swap** = implement one new adapter class. Zero node/graph changes.
- **Testing** = inject a `MockAdapter` at test time. Real engines never run in CI.
- **Per-stage isolation** = each stage's engine can be upgraded, reconfigured, or replaced independently of the others.
- **Small engine principle** = each adapter wraps a *small*, focused engine with a narrow interface. The adapter is the only place that knows the engine's API shape, configuration, and error vocabulary.

### 5.2 Adapter Architecture

```
LangGraph Nodes (graph.py, nodes.py)
    │
    │  (depend on protocols only — never on concrete engines)
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         ADAPTER LAYER                                    │
│                                                                          │
│  Protocol (uniform)        Concrete Adapter (engine-specific)           │
│  ─────────────────         ──────────────────────────────                │
│  GlossaryAdapter           SQLiteGlossaryAdapter  → sqlite3              │
│                             DuckDBGlossaryAdapter  → duckdb (future)     │
│                                                                          │
│  RetrievalAdapter           ChromaRetrievalAdapter → chromadb            │
│                             DuckDBRetrievalAdapter → duckdb (future)     │
│                                                                          │
│  LLMEngineAdapter           OllamaEngineAdapter   → ollama               │
│                             LlamaCppEngineAdapter → llama.cpp server     │
│                             MockEngineAdapter      → deterministic mock  │
│                                                                          │
│  EmbeddingAdapter           OllamaEmbeddingAdapter → ollama (nomic)      │
│                             MockEmbeddingAdapter    → deterministic mock │
└─────────────────────────────────────────────────────────────────────────┘
    │
    │  (adapters call concrete engines — the ONLY place engine APIs appear)
    │
    ▼
Concrete Engines: sqlite3, chromadb, ollama, llama.cpp, ...
```

### 5.3 Per-Stage Adapter Protocols

Each pipeline stage has its own adapter protocol. A stage's adapter wraps exactly one small engine and exposes a narrow interface.

#### GlossaryAdapter

```python
@runtime_checkable
class GlossaryAdapter(Protocol):
    def load(self, glossary_files: list[Path]) -> None:
        """Load glossary terms from JSON files into the engine index."""
        ...

    def scan(self, text: str, lang: str) -> list[GlossaryHit]:
        """Scan input text for glossary term matches. Returns hits with offsets."""
        ...
```

**Concrete**: `SQLiteGlossaryAdapter` wraps `sqlite3`. The adapter owns the connection lifecycle, normalization logic, and longest-match algorithm. The node calls `adapter.scan(text, lang)` — it never sees SQL.

#### RetrievalAdapter

```python
@runtime_checkable
class RetrievalAdapter(Protocol):
    def ingest(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Add chunks + embeddings to the vector store."""
        ...

    def retrieve(self, query_embedding: list[float], n_results: int,
                 where: dict | None = None) -> list[ContextChunk]:
        """Query the vector store for the top-k most similar chunks."""
        ...

    def rebuild(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Atomically rebuild the entire index."""
        ...
```

**Concrete**: `ChromaRetrievalAdapter` wraps `chromadb.PersistentClient`. The adapter owns HNSW parameters, batch sizing, atomic swap logic, and file-handle cleanup. The node calls `adapter.retrieve(...)` — it never sees ChromaDB's API.

#### LLMEngineAdapter

```python
@runtime_checkable
class LLMEngineAdapter(Protocol):
    def generate(self, system_prompt: str, user_prompt: str, *,
                 model: str, temperature: float = 0.0,
                 max_tokens: int = 2048, timeout: float = 120.0) -> str:
        """Run inference. Returns text output. Raises domain exceptions on failure."""
        ...
```

**Concrete implementations**:
- `OllamaEngineAdapter` — wraps the `ollama` Python client. Translates `ollama.ResponseError`, `httpx.ConnectError`, `httpx.ReadTimeout` into `OllamaConnectionError`, `OllamaTimeoutError`, `OllamaModelNotLoadedError`.
- `LlamaCppEngineAdapter` (future) — wraps an HTTP client talking to `llama.cpp`'s server mode. Translates its error vocabulary into the same domain exceptions.
- `MockEngineAdapter` — deterministic, returns canned responses. Used in all tests.

Both the Translator node and the Auditor node receive an `LLMEngineAdapter` instance. They do not know (or care) whether it is Ollama, LlamaCpp, or Mock.

#### EmbeddingAdapter

```python
@runtime_checkable
class EmbeddingAdapter(Protocol):
    def embed(self, text: str) -> list[float]:
        """Embed a single text. Returns a float vector."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Batch size is controlled by the adapter."""
        ...
```

**Concrete**: `OllamaEmbeddingAdapter` wraps the `nomic-embed-text` model via Ollama. `MockEmbeddingAdapter` returns hash-based deterministic vectors for CI.

### 5.4 Adapter Composition at Graph Construction

Adapters are injected at graph build time. The graph is constructed once per process with a specific adapter set, then reused for all translation runs:

```python
# src/graph.py
def build_graph(
    glossary_adapter: GlossaryAdapter,
    retrieval_adapter: RetrievalAdapter,
    embedding_adapter: EmbeddingAdapter,
    llm_adapter: LLMEngineAdapter,
    config: AppConfig,
) -> CompiledGraph:
    graph = StateGraph(TranslationState)

    graph.add_node("preprocess", lambda s: preprocess_node(
        s, glossary_adapter, retrieval_adapter, embedding_adapter, config))
    graph.add_node("translate", lambda s: translate_node(s, llm_adapter, config))
    graph.add_node("audit", lambda s: audit_node(s, llm_adapter, config))
    graph.add_node("finalize", finalize_node)
    # ... edges and conditional routing ...
    return graph.compile()
```

### 5.5 Adapter Selection (CLI entry point)

The CLI constructs the concrete adapter set based on `config.yaml` and command-line flags:

```python
# src/cli.py
def build_adapters(config: AppConfig) -> AdapterSet:
    if config.llm_backend == "ollama":
        llm = OllamaEngineAdapter(host=config.ollama_host)
        embed = OllamaEmbeddingAdapter(host=config.ollama_host, model=config.embed_model)
    elif config.llm_backend == "llamacpp":
        llm = LlamaCppEngineAdapter(url=config.llamacpp_url)
        embed = LlamaCppEmbeddingAdapter(url=config.llamacpp_url, model=config.embed_model)
    else:
        raise ConfigError(f"Unknown LLM backend: {config.llm_backend}")

    glossary = SQLiteGlossaryAdapter(db_path=config.glossary_db_path)
    retrieval = ChromaRetrievalAdapter(persist_dir=config.chroma_dir)

    return AdapterSet(glossary=glossary, retrieval=retrieval,
                      embedding=embed, llm=llm)
```

### 5.6 Adapter Contract Rules

1. **Adapters translate engine errors into domain exceptions.** An adapter MUST catch all engine-specific exceptions and re-raise as the appropriate `LegalTranslationError` subclass. No engine exception type ever escapes the adapter boundary. (See `clean-code` skill §3 for the exception matrix.)
2. **Adapters own resource lifecycle.** The adapter opens, manages, and closes the engine connection. The node never holds a reference to the underlying engine.
3. **Adapters are stateless across calls** (except for connection state). An adapter does not cache translation results or glossary scans — that is the node's or state's responsibility.
4. **One adapter = one engine.** An adapter never wraps two engines. If a stage needs two engines, it gets two adapters.
5. **Adapters are the only import boundary.** `import sqlite3`, `import chromadb`, `import ollama` appear ONLY in adapter implementation files (`src/adapters/*.py`). A grep for these imports in `nodes.py`, `graph.py`, or `cli.py` is a CI failure.

### 5.7 File Layout

```
src/
├── adapters/
│   ├── __init__.py
│   ├── protocols.py          # GlossaryAdapter, RetrievalAdapter, LLMEngineAdapter, EmbeddingAdapter
│   ├── glossary_sqlite.py    # SQLiteGlossaryAdapter
│   ├── retrieval_chroma.py   # ChromaRetrievalAdapter
│   ├── llm_ollama.py         # OllamaEngineAdapter
│   ├── llm_llamacpp.py       # LlamaCppEngineAdapter (future)
│   ├── llm_mock.py           # MockEngineAdapter
│   ├── embedding_ollama.py   # OllamaEmbeddingAdapter
│   └── embedding_mock.py     # MockEmbeddingAdapter
├── nodes.py                  # imports from adapters.protocols only
├── graph.py                  # imports from adapters.protocols only
└── cli.py                    # imports concrete adapters for construction
```

---

## 6. Memory & Latency Budget

Target end-to-end latency for a single article (≤ 500 tokens source):

| Stage | Target | Notes |
|---|---|---|
| Preprocess (glossary + retrieval) | < 400 ms | SQLite + ChromaDB local |
| Translator (1 call) | 6–12 s | 7B q5 on CPU/GPU hybrid |
| Auditor (1 call) | 4–8 s | Shorter output |
| Worst case (3 revisions) | ~60 s | Bounded |

Peak RSS during a run must remain **≤ 6 GB** to leave 2 GB OS headroom on the 8 GB target.

---

## 7. Failure Modes & Mitigations

| Failure | Mitigation |
|---|---|
| Ollama daemon not running | `doctor` command checks at startup; CLI exits with clear message |
| Model OOM | Hard rule: never load >8B; `doctor` verifies model size |
| ChromaDB corruption | Rebuild from `data/` via `ingestion --rebuild`; DB is a derived artifact |
| Auditor–Translator oscillation | Hard cap of 3 revisions; best-effort emit on cap |
| Glossary conflict (two terms match same span) | Resolved by `priority` then `len(source_term) DESC` |
| Empty retrieval (no relevant chunks) | Translator proceeds with glossary only; warning recorded |
| Adapter engine swap failure | Adapter translates engine errors to domain exceptions; node never sees raw engine errors |
| Unknown LLM backend in config | CLI `build_adapters` raises `ConfigError` at startup before any translation runs |
