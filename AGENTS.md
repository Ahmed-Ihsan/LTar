# AGENTS.md — Iraqi Legal Translation Agent

## OpenSpec — Source of Truth

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for spec-driven development.
**All AI agents working on this project MUST consult the OpenSpec files before making changes.**

### Where the specs live

```
openspec/
├── config.yaml                          # Project context, tech stack, constraints, per-artifact rules
├── specs/                               # Source-of-truth specs (current system behavior)
│   ├── config/spec.md                   # Configuration loading & validation (5 requirements)
│   ├── translation_pipeline/spec.md     # LangGraph state machine, nodes, prompts, exceptions (9 requirements)
│   ├── knowledge_sources/spec.md        # Glossary, retrieval, TM, legal search, ingestion (6 requirements)
│   ├── infrastructure/spec.md           # LLM adapter, embeddings, memory/RAM guard, run logging (4 requirements)
│   └── interfaces/spec.md               # CLI, web UI, Tkinter UI, MCP server, HITL (7 requirements)
└── changes/                             # Change proposals (in-progress & archived)
    └── refactor-to-component-architecture/
        ├── proposal.md                  # WHY the change, scope, migration path, rollback plan
        ├── design.md                    # Target architecture, dependency diagram, decisions
        ├── tasks.md                     # Ordered task list (101 tasks)
        └── specs/                       # Delta specs (ADDED/MODIFIED/REMOVED requirements)
```

### Rules for AI agents

1. **Read before you write.** Before implementing any feature, bugfix, or refactor, read the relevant
   spec(s) in `openspec/specs/<capability>/spec.md`. The specs are the authoritative description of
   expected behavior — each requirement has Given/When/Then scenarios.

2. **Check for active changes.** Run `openspec list` to see in-progress change proposals. If a change
   exists that affects your task, read its `proposal.md`, `design.md`, and `tasks.md` first. Follow
   the task list in `tasks.md` when executing the change.

3. **Specs are the contract.** Every requirement in a spec MUST be preserved unless a change proposal
   explicitly marks it as MODIFIED or REMOVED. Do not silently change behavior that a spec documents.

4. **New work needs a change proposal.** For any non-trivial change (new feature, refactor, behavior
   modification), create an OpenSpec change first:
   ```
   openspec new change <change-name> --goal "<one-sentence goal>"
   ```
   Then write `proposal.md` → `specs/` (delta) → `design.md` → `tasks.md` in that order.
   Validate with `openspec validate <change-name>` before implementing.

5. **Validate after changes.** After implementing, run:
   ```
   openspec validate --all
   ```
   All specs and changes must pass. If a change is complete, archive it:
   ```
   openspec archive <change-name>
   ```

6. **Use the project context.** `openspec/config.yaml` contains the tech stack, hard constraints
   (8 GB RAM, no cloud calls, single-user), conventions (DI via keyword-only args, TypedDicts for
   state, Pydantic for config, versioned prompts), and per-artifact rules. Follow these.

### Current active change

| Change | Status | Tasks |
|---|---|---|
| `refactor-to-component-architecture` | In progress | 0/101 |

This change restructures the 21 flat `src/` modules into 4 bounded-context components + a config
package, each with a `models.py`. See `openspec/changes/refactor-to-component-architecture/` for
the full proposal, design, and task list. **Do not start implementing without reading the design.**

### Useful OpenSpec commands

| Command | Purpose |
|---|---|
| `openspec list --specs` | List all source-of-truth specs |
| `openspec list` | List all change proposals |
| `openspec validate --all` | Validate all specs and changes |
| `openspec validate <change-name>` | Validate a single change |
| `openspec status --change <name>` | Show artifact completion status |
| `openspec show <name>` | Display a change or spec |
| `openspec new change <name> --goal "..."` | Create a new change proposal |
| `openspec archive <name>` | Archive a completed change into specs |
| `openspec context` | Print working context and root |

---

## Project Overview

Local, offline-first Agentic RAG system for translating Iraqi legal texts (Arabic ⇄ English).
LangGraph orchestrates a Translate → Audit → Revise loop with deterministic glossary enforcement,
ChromaDB retrieval, Translation Memory, and dual-agent quality assurance.

## Tech Stack

- **Language:** Python 3.11.x (exact minor; test venv runs 3.10)
- **Agent orchestration:** LangGraph >= 0.2, < 0.3
- **LLM runtime:** Ollama (local daemon), qwen2.5:7b-instruct-q5_K_M
- **Embeddings:** nomic-embed-text via Ollama (768-dim)
- **Vector store:** ChromaDB >= 0.5 (PersistentClient only)
- **Relational store:** SQLite3 (stdlib) — glossary + TM
- **CLI:** Typer >= 0.12 + Rich >= 13.7
- **Desktop UI:** pywebview (web_ui) + Tkinter (tk_ui)
- **MCP server:** FastMCP
- **Config:** Pydantic >= 2.6 + PyYAML
- **Dev tooling:** pytest, ruff (line-length 100), mypy (strict), radon

## Hard Constraints

- 8 GB RAM hard ceiling; never load models > 8B params
- ChromaDB PersistentClient only — never client/server mode
- Concurrent in-flight requests = 1 (no parallel translation jobs)
- Embedding batch size capped at 32; LLM context window capped at 8192 tokens
- No cloud LLM calls, no telemetry, no third-party network calls
- Single-user, single-session

## Conventions

- Conventional commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`
- Dependency Injection via keyword-only args (DIP)
- Protocols (PEP 544) for adapter seams: `LLMEngineAdapter`, `EmbeddingAdapter`, `HumanReviewer`
- TypedDicts (PEP 692) for LangGraph state; Pydantic models for configuration only
- Prompts are versioned constants (V1–V4); V4 is current default
- Exception hierarchy rooted at `LegalTranslationError`
- Bilingual scenarios (Arabic + English) in specs where applicable

## Verification Commands

```powershell
# Tests
pytest --tb=short -q

# Lint
ruff check src/ tests/

# Type-check
mypy src/

# Complexity
radon cc src/ -a

# OpenSpec validation
openspec validate --all

# Smoke test
python -m src.cli doctor
python -m src.cli translate --input "المادة ١" --direction ar-en
```

## Current Architecture (flat src/ — being refactored)

```
src/
├── cli.py, config.py, state.py, graph.py, nodes.py, decision.py
├── prompts.py, exceptions.py, glossary.py, retrieval.py, tm.py
├── legal_search.py, ingestion.py, llm.py, embeddings.py, memory.py
├── run_logging.py, hitl.py, web_ui.py, tk_ui.py, mcp_server.py
└── __init__.py
```

See `openspec/changes/refactor-to-component-architecture/design.md` for the target component + models architecture.
