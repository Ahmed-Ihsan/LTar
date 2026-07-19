# Iraqi Legal Translation Agent

> A local, offline-first Agentic RAG system for translating Iraqi legal texts (Arabic ⇄ English) with strict terminology adherence, deterministic glossary enforcement, and dual-agent quality assurance.

---

## 1. Executive Summary

The **Iraqi Legal Translation Agent** is a fully local, privacy-preserving translation pipeline built for Iraqi statutory and jurisprudential text. It combines a deterministic **Exact-Match Glossary** (SQLite + JSON) with a **ChromaDB** vector store of Iraqi laws, and orchestrates two specialized LLM agents — a **Translator** and an **Auditor** — through **LangGraph**.

The system is engineered to run on commodity consumer hardware with **8 GB RAM** as the hard ceiling. The default LLM backend is **Ollama** running a quantized local model, so no external API calls are required. An **opt-in** Google Gemini API cloud backend (`llm_backend: gemini`) is the only sanctioned cloud path; when it is disabled (the default), no component transmits data off the host. This makes the system suitable for offline field deployment, law offices with air-gapped networks, and jurisdictions where legal data must not leave the workstation.

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

## 2. Quick Start (How to Run)

This section is the fast path from a clean clone to a working translation in
under 10 minutes. For the deeper, annotated setup reference see
[§6 Setup, Installation, and Run](#6-setup-installation-and-run).

### Prerequisites

- Windows 10/11 or Linux
- 8 GB RAM minimum
- Python 3.10.x or 3.11.x
- Ollama installed (https://ollama.com)
- ~10 GB free disk (models + vector store)

### 2.1 Pull models

```powershell
ollama pull gemma3:4b
ollama pull nomic-embed-text
ollama list
```

### 2.2 Create venv and install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

> **Windows launcher note:** `run.bat` invokes
> `.\.venv310\Scripts\python.exe`, so it expects the virtual environment to be
> named **`.venv310`** (not `.venv`). If you intend to use `run.bat`, create the
> venv with `python -m venv .venv310` instead. Both names work with the CLI
> commands below; only the launcher is hard-coded to `.venv310`.

### 2.3 Configure

Defaults in [`config.yaml`](config.yaml) target the 8 GB RAM offline profile
and need no edits for a first run. The one key to know about is `llm_backend`:

- **`ollama`** (default) — local daemon, offline. Requires `ollama serve` and
  the two models from [§2.1](#21-pull-models).
- **`llamacpp`** — local llama.cpp server (offline). Point `llamacpp_url` at
  your server.
- **`gemini`** — opt-in Google Gemini API cloud backend. Requires the
  `GEMINI_API_KEY` environment variable (never written to `config.yaml`); the
  `google-genai` SDK is lazily imported so offline users never import it.

```powershell
# Only if you choose the Gemini backend:
$env:GEMINI_API_KEY = "your-api-key-here"
# In config.yaml:  llm_backend: gemini
```

### 2.4 Ingest the corpus

```powershell
python -m src.app ingest
```

This parses `data/corpus/*`, chunks and embeds the text via Ollama into
`db/chroma/`, and loads `data/glossary/*.json` into `db/glossary.sqlite`.

### 2.5 Run

#### a) Windows launcher (easiest)

Double-click **`run.bat`** for an interactive menu with 8 options:

| # | Menu option | What it runs |
|---|---|---|
| 1 | Doctor | `python -m src.app doctor` — environment diagnostics |
| 2 | Translate AR → EN | `translate --input "<text>" --direction ar-en` |
| 3 | Translate EN → AR | `translate --input "<text>" --direction en-ar` |
| 4 | Batch translate | `batch --input <jsonl> --out <jsonl>` |
| 5 | Ingest corpus | `ingest` |
| 6 | Build TM | `tm-build` |
| 7 | Launch UI | `ui` |
| 8 | Exit | quits |

#### b) CLI

```powershell
# Check environment
python -m src.app doctor

# Translate a single sentence (Arabic -> English)
python -m src.app translate --input "المادة ١" --direction ar-en

# Translate a single sentence (English -> Arabic)
python -m src.app translate --input "Article 1" --direction en-ar

# Batch translate from JSONL (--out, not --output)
python -m src.app batch --input data/batch.jsonl --out data/results.jsonl

# Build Translation Memory from corpus
python -m src.app tm-build

# Launch the desktop UI
python -m src.app ui
```

Additional commands (see [§6.6](#66-run-the-agent) for full reference):
`excel` (translate an `.xlsx` workbook), `tm-build-parallel`, `tm-add-parallel`.

#### c) Desktop UI

```powershell
python -m src.app ui
```

`ui.backend: web` (default) launches the pywebview desktop UI; set
`ui.backend: tk` in [`config.yaml`](config.yaml) for the Tkinter UI (native
widgets, no browser dependency).

### 2.6 Verify

```powershell
python -m src.app doctor
```

`doctor` checks (backend-dependent) that the daemon is reachable, the required
models are present, the ChromaDB directory and glossary SQLite are populated,
and the RAM headroom estimate fits the 8 GB ceiling. All checks passed = ready.

### Troubleshooting

- **Garbled Arabic output on Windows:** set
  `$env:PYTHONIOENCODING='utf-8'` (PowerShell) before running. `run.bat` sets
  this automatically.
- **Exit code 4 (path containment):** `--input` and `--out` paths must be
  inside the project root. Paths outside the root are rejected.
- **Ollama daemon not running:** start it with `ollama serve` (or launch the
  Ollama desktop app).
- **Missing models:** run `ollama list`; if `gemma3:4b` or `nomic-embed-text`
  is absent, re-run the `ollama pull` commands from [§2.1](#21-pull-models).
- **Gemini key missing:** when `llm_backend: gemini`, `GEMINI_API_KEY` must be
  set in the environment or `doctor`/`translate` exit with an error.

---

## 3. Tech Stack

| Layer | Technology | Version / Constraint |
|---|---|---|
| Language | Python | 3.10.x or 3.11.x |
| Agent Orchestration | LangGraph | `langgraph >= 0.2, < 0.3` |
| LLM Runtime | Ollama (default), llama.cpp, or Google Gemini API (opt-in) | Local daemon `ollama serve`, local `llamacpp_url` server, or cloud `google-genai >= 1.0, < 2` |
| LLM Model | `gemma3:4b` (Ollama/llama.cpp) / `gemini-2.0-flash` (Gemini) | Quantized, ≤ 2 GB footprint (Ollama); cloud-hosted (Gemini) |
| Embeddings | `nomic-embed-text` via Ollama / `text-embedding-004` via Gemini | 768-dim, CPU-friendly (Ollama); 768-dim cloud (Gemini) |
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
- **Optional Google Gemini API backend**: an opt-in cloud path (`llm_backend: gemini` in `config.yaml`) for users who prefer hosted inference. The `google-genai` SDK is lazily imported — offline users on the Ollama path never import it. The Gemini free-tier RPM cap (default 15) is enforced by a process-local sliding-window rate limiter.
- **ChromaDB**: embedded, file-backed, no server process — minimizes resident memory.
- **SQLite + JSON glossary**: deterministic override layer that does not depend on the LLM, guaranteeing term consistency even when the model drifts.
- **LangGraph**: explicit state machine for the Translate → Audit → Revise loop, with conditional edges and bounded retry.

---

## 4. Hardware Target Constraints (8 GB RAM)

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

## 5. Project Structure

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
└── tests/                       # 465 tests
```

---

## 6. Setup, Installation, and Run

> This is the deeper, annotated setup reference. For the fast path see
> [§2 Quick Start (How to Run)](#2-quick-start-how-to-run).

### 6.1 Prerequisites

- Windows 10/11 (or Linux equivalent), 8 GB RAM minimum.
- **Ollama** installed: https://ollama.com (Windows installer).
- Python 3.10.x or 3.11.x verified via `python --version`.
- ~10 GB free disk for models + vector store.

### 6.2 Install Ollama Models

```powershell
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

Verify both are available:

```powershell
ollama list
```

### 6.3 Create Environment and Install Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

`requirements.txt` is the canonical install list — it includes every runtime
dependency needed for the CLI and the desktop UI (including `pywebview`,
`defusedxml` for XXE-safe XML parsing, and `pyahocorasick` for fast glossary
term matching). `pyproject.toml` mirrors it for editable installs
(`pip install -e .`); both install paths produce the same runtime environment.

**Path containment:** All `--input` and `--out` paths must be inside the
project root directory. Paths outside the root are rejected with exit code 4.

**Optional dependencies:**

`gradio` is optional and not required for the CLI or desktop UI. To install it,
uncomment the `gradio` line at the bottom of `requirements.txt` or run:

```powershell
pip install -e .[gradio]
```

### 6.4 Configure

Edit `config.yaml` to set model names, paths, and chunk parameters. Defaults target the 8 GB RAM profile.

The `ui.backend` key selects which desktop UI to launch via `iraqi-translate ui`:
`web` (pywebview, default) or `tk` (Tkinter, no browser dependency).

#### LLM backend selection

The `llm_backend` key selects the inference backend:

- **`ollama`** (default) — local daemon, no network. Requires `ollama serve`
  and the models from [§6.2](#62-install-ollama-models).
- **`llamacpp`** — local llama.cpp server (offline). Point `llamacpp_url`
  (default `http://localhost:8080`) at your server. Reuses the same Ollama-style
  adapter and `doctor` checks as the `ollama` backend.
- **`gemini`** — opt-in Google Gemini API cloud backend. Requires the
  `GEMINI_API_KEY` environment variable (never written to `config.yaml`).
  The `google-genai` SDK is lazily imported; offline users on the Ollama
  path never import it. Gemini-specific keys (`gemini_model`,
  `gemini_embed_model`, `gemini_timeout`, `gemini_rpm`) tune the cloud
  backend; the default RPM cap is 15 (Gemini free-tier).

```powershell
# Switch to the Gemini backend (PowerShell)
$env:GEMINI_API_KEY = "your-api-key-here"
# In config.yaml:  llm_backend: gemini
python -m src.app doctor   # verifies the key + API reachability
```

### 6.5 Ingest the Corpus

```powershell
python -m src.app ingest
```

This parses `data/corpus/*`, chunks the text, embeds via Ollama, and writes to `db/chroma/`. It also loads `data/glossary/*.json` into `db/glossary.sqlite`.

### 6.6 Run the Agent

**Quick start (Windows):** Double-click `run.bat` for an interactive menu.

**CLI commands:**

```powershell
# Check environment
python -m src.app doctor

# Translate a single sentence
python -m src.app translate --input "المادة ١" --direction ar-en
python -m src.app translate --input "Article 1" --direction en-ar

# Batch translate from JSONL (--out, not --output)
python -m src.app batch --input data/batch.jsonl --out data/results.jsonl

# Translate an Excel workbook (preserves formulas, charts, merged cells, etc.)
python -m src.app excel --input data/source.xlsx --out data/translated.xlsx --direction ar-en

# Build Translation Memory from corpus
python -m src.app tm-build
python -m src.app tm-build-parallel   # parallel TM build
python -m src.app tm-add-parallel     # add parallel sentence pairs to TM

# Launch desktop UI (pywebview)
python -m src.app ui
```

> **Path containment:** `--input` and `--out` paths must be inside the project
> root. Paths outside the root are rejected with exit code 4.

> **Note:** On Windows, set UTF-8 encoding for Arabic output:
> ```powershell
> $env:PYTHONIOENCODING='utf-8'
> ```

### 6.7 Verify the Installation

```powershell
python -m src.app doctor
```

The `doctor` command checks (backend-dependent):

- **Ollama / llama.cpp backend** (`llm_backend: ollama` (default) or
  `llamacpp`): Ollama daemon reachable, required local models present,
  ChromaDB directory initialized, glossary SQLite populated, full RAM headroom
  estimate (LLM weight budget included).
- **Gemini backend** (`llm_backend: gemini`): `GEMINI_API_KEY` present,
  Gemini API reachable (list-models ping), ChromaDB directory initialized,
  glossary SQLite populated, reduced RAM headroom estimate (cloud LLM — no
  local weights).

### 6.8 Logging

All entry points (CLI, web UI, Tkinter UI) call `configure_logging()` from
`src/utils/logging_setup.py` before any component runs. Logs are written to
**stderr** with format `%(asctime)s %(levelname)s %(name)s %(message)s` and,
when a `log_dir` is configured (default: `logs/`), also to
`logs/app.log` (UTF-8, appended). The logging level defaults to `INFO` and
can be set via `config.yaml`. The setup is idempotent — repeated calls do not
add duplicate handlers.

---

## 7. Architecture

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

## 8. Development

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

## 9. Non-Goals

- No cloud LLM calls except the opt-in Google Gemini API backend
  (`llm_backend: gemini`). No OpenAI, Anthropic, or any other remote inference.
- No multi-tenant serving. Single-user, single-session.
- No fine-tuning pipeline in this repository. Glossary + RAG is the alignment strategy.
- No translation of non-Iraqi legal systems (e.g., Egyptian, French law) unless explicitly added to the corpus.

---

## 10. License & Data Handling

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

All Iraqi statutory text used in the corpus must be sourced from public official gazette publications. No component of this system transmits data off the host machine.
