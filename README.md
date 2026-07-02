# Iraqi Legal Translation Agent

> A local, offline-first Agentic RAG system for translating Iraqi legal texts (Arabic ⇄ English) with strict terminology adherence, deterministic glossary enforcement, and dual-agent quality assurance.

---

## 1. Executive Summary

The **Iraqi Legal Translation Agent** is a fully local, privacy-preserving translation pipeline built for Iraqi statutory and jurisprudential text. It combines a deterministic **Exact-Match Glossary** (SQLite + JSON) with a **ChromaDB** vector store of Iraqi laws, and orchestrates two specialized LLM agents — a **Translator** and an **Auditor** — through **LangGraph**.

The system is engineered to run on commodity consumer hardware with **8 GB RAM** as the hard ceiling. No external API calls are made; all inference is served by **Ollama** running a quantized local model. This makes the system suitable for offline field deployment, law offices with air-gapped networks, and jurisdictions where legal data must not leave the workstation.

### Core Capabilities

- Arabic → English and English → Arabic translation of Iraqi legal clauses.
- Term-level enforcement via an Exact-Match Glossary that overrides LLM output before and after generation.
- Retrieval-Augmented Generation over a corpus of Iraqi laws (Civil Code, Penal Code, Civil Procedure Code, etc.).
- Two-stage quality control: Translator produces a draft, Auditor either approves or returns it for revision with a structured critique.
- Deterministic, reproducible runs — no network dependency, no telemetry, no third-party calls.

---

## 2. Tech Stack

| Layer | Technology | Version / Constraint |
|---|---|---|
| Language | Python | 3.11.x (exact minor required) |
| Agent Orchestration | LangGraph | `langgraph >= 0.2` |
| LLM Runtime | Ollama | Local daemon, `ollama serve` |
| LLM Model | `qwen2.5:7b-instruct-q5_K_M` or `llama3.1:8b-instruct-q4_K_M` | Quantized, ≤ 5 GB footprint |
| Embeddings | `nomic-embed-text` via Ollama | 768-dim, CPU-friendly |
| Vector Store | ChromaDB | `chromadb >= 0.5`, persistent local directory |
| Relational Store | SQLite3 (stdlib) | Glossary exact-match index |
| Glossary Source | JSON files | Human-editable, version-controlled |
| CLI / UI | `Typer` + `Rich` (CLI), optional `Gradio` (UI) | Local only |
| Packaging | `uv` or `pip` + `venv` | No conda dependency |

### Why these choices

- **Ollama + quantized 7B/8B model**: fits the 8 GB RAM envelope alongside the embedding model and ChromaDB process. Larger models (14B+) are explicitly out of scope.
- **ChromaDB**: embedded, file-backed, no server process — minimizes resident memory.
- **SQLite + JSON glossary**: deterministic override layer that does not depend on the LLM, guaranteeing term consistency even when the model drifts.
- **LangGraph**: explicit state machine for the Translate → Audit → Revise loop, with conditional edges and bounded retry.

---

## 3. Hardware Target Constraints (8 GB RAM)

The system is designed against a **hard 8 GB RAM** ceiling. The following budget must be respected at all times:

| Component | Target RSS | Notes |
|---|---|---|
| OS + desktop shell | ~1.8 GB | Windows 11 baseline |
| Ollama LLM (q5_K_M 7B) | ~3.0 GB | Mapped, not fully resident |
| Ollama embed model | ~0.3 GB | `nomic-embed-text` |
| ChromaDB (embedded) | ~0.5 GB | Persistent client, no server |
| Python interpreter + app | ~0.4 GB | LangGraph, Typer, libs |
| **Headroom** | **~2.0 GB** | Reserved for chunk ingestion spikes |

### Hard Rules

1. **Never** load a model larger than 8B parameters. Quantization must be `q4_K_M` or lower-bit (`q5_K_M` acceptable for 7B).
2. **Never** run ChromaDB in client/server mode on the same machine — use `PersistentClient` only.
3. **Never** hold the full corpus in memory. Ingestion streams documents in batches of ≤ 64 chunks.
4. Embedding batch size capped at **32**; LLM context window capped at **8192 tokens**.
5. Concurrent in-flight requests = **1**. No batching of multiple translation jobs in parallel.

---

## 4. Project Structure

```
translater/
├── README.md
├── ARCHITECTURE.md
├── PROMPTS.md
├── DATA_SPEC.md
├── TODO.md
├── requirements.txt
├── pyproject.toml
├── config.yaml
├── data/
│   ├── glossary/
│   │   ├── civil_code.json
│   │   ├── penal_code.json
│   │   └── procedural_terms.json
│   ├── corpus/
│   │   ├── civil_code_en.txt
│   │   ├── civil_code_ar.txt
│   │   └── ...
│   └── raw/
├── db/
│   ├── glossary.sqlite
│   └── chroma/              # ChromaDB persistent directory
├── src/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── glossary.py
│   ├── ingestion.py
│   ├── embeddings.py
│   ├── retrieval.py
│   ├── graph.py             # LangGraph definition
│   ├── nodes.py             # translator + auditor nodes
│   ├── state.py             # TypedDict state schema
│   └── prompts.py
└── tests/
```

---

## 5. Setup, Installation, and Run

### 5.1 Prerequisites

- Windows 10/11 (or Linux equivalent), 8 GB RAM minimum.
- **Ollama** installed: https://ollama.com (Windows installer).
- Python 3.11.x verified via `python --version`.
- ~10 GB free disk for models + vector store.

### 5.2 Install Ollama Models

```powershell
ollama pull qwen2.5:7b-instruct-q5_K_M
ollama pull nomic-embed-text
```

Verify both are available:

```powershell
ollama list
```

### 5.3 Create Environment and Install Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5.4 Configure

Edit `config.yaml` to set model names, paths, and chunk parameters. Defaults target the 8 GB RAM profile.

### 5.5 Ingest the Corpus

```powershell
python -m src.ingestion --rebuild
```

This parses `data/corpus/*`, chunks according to `DATA_SPEC.md`, embeds via Ollama, and writes to `db/chroma/`. It also loads `data/glossary/*.json` into `db/glossary.sqlite`.

### 5.6 Run the Agent

CLI (default interface):

```powershell
python -m src.cli translate --input "المادة ١ من القانون المدني" --direction ar-en
```

Optional Gradio UI:

```powershell
python -m src.cli ui
```

### 5.7 Verify the Installation

```powershell
python -m src.cli doctor
```

The `doctor` command checks: Ollama daemon reachable, required models present, ChromaDB directory initialized, glossary SQLite populated, RAM headroom estimate.

---

## 6. Non-Goals

- No cloud LLM calls. No OpenAI, Anthropic, or any remote inference.
- No multi-tenant serving. Single-user, single-session.
- No fine-tuning pipeline in this repository. Glossary + RAG is the alignment strategy.
- No translation of non-Iraqi legal systems (e.g., Egyptian, French law) unless explicitly added to the corpus.

---

## 7. License & Data Handling

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

All Iraqi statutory text used in the corpus must be sourced from public official gazette publications. No component of this system transmits data off the host machine.
