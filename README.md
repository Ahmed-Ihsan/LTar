# Iraqi Legal Translation Agent

> A local, offline-first Agentic RAG system for translating Iraqi legal texts (Arabic ⇄ English) with strict terminology adherence, deterministic glossary enforcement, and dual-agent quality assurance.

---

## 1. Executive Summary

The **Iraqi Legal Translation Agent** is a fully local, privacy-preserving translation pipeline built for Iraqi statutory and jurisprudential text. It combines a deterministic **Exact-Match Glossary** (SQLite + JSON) with a **ChromaDB** vector store of Iraqi laws, and orchestrates two specialized LLM agents — a **Translator** and an **Auditor** — through **LangGraph**.

The system is engineered to run on commodity consumer hardware with **8 GB RAM** as the hard ceiling. No external API calls are made; all inference is served by **Ollama** running a quantized local model. This makes the system suitable for offline field deployment, law offices with air-gapped networks, and jurisdictions where legal data must not leave the workstation.

### Core Capabilities

- Arabic → English and English → Arabic translation of Iraqi legal clauses.
- Term-level enforcement via an Exact-Match Glossary that overrides LLM output before and after generation.
- Retrieval-Augmented Generation over a corpus of Iraqi laws (Civil Code, Penal Code, Civil Procedure Code, Commercial Code, etc.).
- Two-stage quality control: Translator produces a draft, Auditor either approves or returns it for revision with a structured critique.
- Translation Memory (TM) for instant reuse of previously translated sentences.
- Human-in-the-loop (HITL) review with correction persistence for future fine-tuning.
- Web search integration for Iraqi legal sources (optional).
- Deterministic, reproducible runs — no network dependency, no telemetry, no third-party calls.

---

## 2. Tech Stack

| Layer | Technology | Version / Constraint |
|---|---|---|
| Language | Python | 3.10.x or 3.11.x |
| Agent Orchestration | LangGraph | `langgraph >= 0.2, < 0.3` |
| LLM Runtime | Ollama | Local daemon, `ollama serve` |
| LLM Model | `gemma3:4b` | Quantized, ≤ 2 GB footprint |
| Embeddings | `nomic-embed-text` via Ollama | 768-dim, CPU-friendly |
| Vector Store | ChromaDB | `chromadb >= 0.5`, persistent local directory |
| Relational Store | SQLite3 (stdlib) | Glossary + Translation Memory |
| Glossary Source | JSON files | Human-editable, version-controlled |
| CLI | Typer + Rich | Local only |
| Desktop UI | pywebview (web_ui) + Tkinter (tk_ui) | Native window, no browser |
| MCP Server | FastMCP | Optional, for IDE integration |
| Config | Pydantic + PyYAML | Typed, validated |
| Dev Tooling | pytest, ruff, mypy (strict), radon | — |

### Why these choices

- **Ollama + quantized 4B model**: fits the 8 GB RAM envelope alongside the embedding model and ChromaDB process. Larger models (14B+) are explicitly out of scope.
- **ChromaDB**: embedded, file-backed, no server process — minimizes resident memory.
- **SQLite + JSON glossary**: deterministic override layer that does not depend on the LLM, guaranteeing term consistency even when the model drifts.
- **LangGraph**: explicit state machine for the Translate → Audit → Revise loop, with conditional edges and bounded retry.

---

## 3. Hardware Target Constraints (8 GB RAM)

The system is designed against a **hard 8 GB RAM** ceiling. The following budget must be respected at all times:

| Component | Target RSS | Notes |
|---|---|---|
| OS + desktop shell | ~1.8 GB | Windows 11 baseline |
| Ollama LLM (gemma3:4b) | ~0.9 GB | GPU offload |
| Ollama embed model | ~0.3 GB | `nomic-embed-text` |
| ChromaDB (embedded) | ~0.5 GB | Persistent client, no server |
| Python interpreter + app | ~0.4 GB | LangGraph, Typer, libs |
| **Headroom** | **~4.1 GB** | Reserved for chunk ingestion spikes |

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
├── requirements.txt
├── pyproject.toml
├── pytest.ini
├── config.yaml                  # Runtime configuration
├── run.bat                      # Windows launcher (interactive menu)
├── data/
│   ├── glossary/                # JSON glossary sources
│   │   ├── civil_code.json
│   │   ├── civil_procedure_code.json
│   │   ├── penal_code.json
│   │   ├── commercial_code.json
│   │   └── un_international.json
│   ├── corpus/                  # Iraqi legal text (AR + EN)
│   └── raw/                     # Raw uploads (gitignored)
├── db/                          # Generated databases (gitignored)
│   ├── glossary.sqlite
│   ├── tm.sqlite
│   └── chroma/
├── openspec/                    # Spec-driven development (source of truth)
│   ├── config.yaml
│   ├── specs/                   # Current system behavior specs
│   └── changes/                 # Change proposals
├── src/
│   ├── app.py                   # DI entry point + console script
│   ├── config/                  # Configuration package
│   │   ├── config.py            # load_config, AppConfig, ConfigError
│   │   ├── cli.py               # Typer CLI for config utilities
│   │   └── models.py            # PathsConfig, ChromaConfig (Pydantic)
│   └── components/              # 4 bounded-context components
│       ├── infrastructure/      # LLM adapter, embeddings, memory, logging
│       ├── knowledge_sources/   # Glossary, retrieval, TM, legal search, ingestion
│       ├── translation_pipeline/ # LangGraph state machine, nodes, prompts
│       └── interfaces/          # CLI, web UI, Tkinter UI, HITL, MCP server
└── tests/                       # 390 tests
```

---

## 5. Setup, Installation, and Run

### 5.1 Prerequisites

- Windows 10/11 (or Linux equivalent), 8 GB RAM minimum.
- **Ollama** installed: https://ollama.com (Windows installer).
- Python 3.10.x or 3.11.x verified via `python --version`.
- ~10 GB free disk for models + vector store.

### 5.2 Install Ollama Models

```powershell
ollama pull gemma3:4b
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
pip install -e .
```

`requirements.txt` is the canonical install list — it includes every runtime
dependency needed for the CLI and the desktop UI (including `pywebview`).
`pyproject.toml` mirrors it for editable installs (`pip install -e .`); both
install paths produce the same runtime environment.

**Optional dependencies:**

`gradio` is optional and not required for the CLI or desktop UI. To install it,
uncomment the `gradio` line at the bottom of `requirements.txt` or run:

```powershell
pip install -e .[gradio]
```

### 5.4 Configure

Edit `config.yaml` to set model names, paths, and chunk parameters. Defaults target the 8 GB RAM profile.

### 5.5 Ingest the Corpus

```powershell
python -m src.app ingest
```

This parses `data/corpus/*`, chunks the text, embeds via Ollama, and writes to `db/chroma/`. It also loads `data/glossary/*.json` into `db/glossary.sqlite`.

### 5.6 Run the Agent

**Quick start (Windows):** Double-click `run.bat` for an interactive menu.

**CLI commands:**

```powershell
# Check environment
python -m src.app doctor

# Translate a single sentence
python -m src.app translate --input "المادة ١" --direction ar-en
python -m src.app translate --input "Article 1" --direction en-ar

# Batch translate from JSONL
python -m src.app batch --input data/batch.jsonl --output data/results.jsonl

# Build Translation Memory from corpus
python -m src.app tm-build

# Launch desktop UI (pywebview)
python -m src.app ui
```

> **Note:** On Windows, set UTF-8 encoding for Arabic output:
> ```powershell
> $env:PYTHONIOENCODING='utf-8'
> ```

### 5.7 Verify the Installation

```powershell
python -m src.app doctor
```

The `doctor` command checks: Ollama daemon reachable, required models present, ChromaDB directory initialized, glossary SQLite populated, RAM headroom estimate.

---

## 6. Architecture

The system follows a **component-based architecture** with 4 bounded contexts:

| Component | Responsibility |
|---|---|
| `infrastructure` | LLM engine adapter, embeddings, RAM guard, run logging |
| `knowledge_sources` | Glossary, ChromaDB retrieval, Translation Memory, legal search, ingestion |
| `translation_pipeline` | LangGraph state machine, translator/auditor nodes, prompts, parsers |
| `interfaces` | CLI, pywebview UI, Tkinter UI, HITL review, MCP server |

**Design principles:** SOLID — each component depends on protocols (PEP 544), not concretions. Adapters are injected via keyword-only args. TypedDicts for state, Pydantic for config, versioned prompts (V1–V4).

See `openspec/` for detailed specs and change proposals.

---

## 7. Development

```powershell
# Run tests
pytest --tb=short -q

# Lint
ruff check src/ tests/

# Type-check
mypy src/

# Complexity
radon cc src/ -a

# Spec validation
openspec validate --all
```

---

## 8. Non-Goals

- No cloud LLM calls. No OpenAI, Anthropic, or any remote inference.
- No multi-tenant serving. Single-user, single-session.
- No fine-tuning pipeline in this repository. Glossary + RAG is the alignment strategy.
- No translation of non-Iraqi legal systems (e.g., Egyptian, French law) unless explicitly added to the corpus.

---

## 9. License & Data Handling

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

All Iraqi statutory text used in the corpus must be sourced from public official gazette publications. No component of this system transmits data off the host machine.
