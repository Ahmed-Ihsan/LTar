# OpenSpec Workflow Skill

## When to Use

Use this skill when:
- The user asks to "propose a change", "create a spec", "add a feature", "refactor", or "make an OpenSpec change"
- You are about to implement a non-trivial change (feature, refactor, bugfix that changes behavior) — create a change proposal FIRST
- The user asks to "validate specs", "archive a change", "check spec status", or "list specs"
- You need to understand the current system behavior — read the source-of-truth specs

**Do NOT use this skill for:**
- Single-line edits or trivial fixes (just do them directly)
- Reading code to answer a question (use grep/read directly)
- Running tests or linting (use exec directly)

## OpenSpec Overview

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) v1.5.0 with the `spec-driven` schema.
The workflow is: **proposal → specs (delta) → design → tasks → implement → validate → archive**.

### Directory structure

```
openspec/
├── config.yaml              # Project context + per-artifact rules (READ THIS FIRST)
├── specs/                   # Source-of-truth specs (current behavior, 5 capabilities)
│   ├── config/spec.md
│   ├── translation_pipeline/spec.md
│   ├── knowledge_sources/spec.md
│   ├── infrastructure/spec.md
│   └── interfaces/spec.md
└── changes/
    ├── <change-name>/       # In-progress change proposal
    │   ├── proposal.md      # WHY + WHAT + capabilities + impact
    │   ├── design.md        # HOW — architecture, decisions, diagrams
    │   ├── tasks.md         # Ordered, checkable task list
    │   └── specs/           # Delta specs (ADDED/MODIFIED/REMOVED requirements)
    └── archive/             # Completed and merged changes
```

## Workflow: Creating a New Change Proposal

### Step 1 — Read context and existing specs

Before writing anything, read:
1. `openspec/config.yaml` — project context, tech stack, constraints, per-artifact rules
2. The relevant source-of-truth spec(s) in `openspec/specs/<capability>/spec.md`
3. `AGENTS.md` — project rules for AI agents

### Step 2 — Create the change directory

```bash
openspec new change <change-name> --goal "<one-sentence goal>" --description "<short description>"
```

- Use kebab-case for the change name (e.g., `add-batch-export`, `fix-tm-threshold`)
- This creates `openspec/changes/<change-name>/` with a `.openspec.yaml` and `README.md`

### Step 3 — Write proposal.md

Write `openspec/changes/<change-name>/proposal.md` following the template and rules:

Required sections (per `openspec/config.yaml` rules):
- **Why** — the motivation, not just the what
- **What Changes** — bullet list, mark **BREAKING** changes
- **Capabilities** — New Capabilities (become `specs/<name>/spec.md`) and Modified Capabilities
- **Impact** — affected code, APIs, dependencies
- **Scope** — explicit "In scope" and "Out of scope" lists
- **Migration path** — file-by-file or step-by-step strategy
- **Rollback plan** — how to revert
- **Affected files** — table of old path → new path
- Reference Event Storming / bounded-context analysis as basis

No implementation code — proposal is about intent and approach.

### Step 4 — Write delta specs

Write `openspec/changes/<change-name>/specs/<capability>/spec.md` for each affected capability.

Format (per `openspec/config.yaml` rules):
```markdown
## ADDED Requirements

### Requirement: <name>
<description with SHALL or MUST keyword>

#### Scenario: <name>
- **GIVEN** <condition>
- **WHEN** <action>
- **THEN** <expected outcome>
```

Rules:
- Use `## ADDED Requirements`, `## MODIFIED Requirements`, or `## REMOVED Requirements` headers
- Every requirement description MUST contain "SHALL" or "MUST" (validator enforces this)
- Every requirement MUST have at least one `#### Scenario:` block
- Use Given/When/Then scenarios
- Include bilingual scenarios (Arabic + English) where behavior is language-dependent
- Delta specs must specify the new module path for every moved symbol
- Preserve all existing behaviors unless explicitly marking a requirement as MODIFIED or REMOVED

### Step 5 — Write design.md

Write `openspec/changes/<change-name>/design.md`:

Required sections (per `openspec/config.yaml` rules):
- **Context** — background and current state
- **Goals / Non-Goals** — what this design aims to achieve and what is out of scope
- **Decisions** — key design decisions with rationale
- **Risks / Trade-offs** — known risks
- **Target directory tree** — full file listing
- **Component dependency diagram** — ASCII or mermaid
- **models.py contents** — every class/TypedDict/protocol per component
- **Inter-component communication protocol** — imports, DI seams
- **Migration strategy** — file-by-file, one move per task
- **app.py / entry point design** — if applicable
- **pyproject.toml changes** — packages, scripts, ruff paths
- **ruff per-file-ignores path migrations** — if applicable

No implementation code beyond illustrative signatures.

### Step 6 — Write tasks.md

Write `openspec/changes/<change-name>/tasks.md`:

Format:
```markdown
## 1. <Task Group Name>

- [ ] 1.1 <task description>
- [ ] 1.2 <task description>
```

Rules (per `openspec/config.yaml` rules):
- Group tasks by component or logical phase
- One file move per task (atomic, verifiable)
- Each task must be independently verifiable (import check, test run, or lint)
- Order tasks so the dependency graph stays satisfiable (foundation first, interfaces last)
- Include a verification task after each component migration
- Include a final full-suite verification task (pytest + ruff + mypy)

### Step 7 — Validate

```bash
openspec validate <change-name>
openspec validate --all
```

Both must pass with 0 failures. If validation fails, read the error messages — they are specific:
- `Requirement must contain SHALL or MUST keyword` → add SHALL/MUST to the requirement description
- `Spec must have a Purpose section` → add `## Purpose` at the top
- `Change must have at least one delta` → write delta specs in `specs/` folder
- `Each requirement MUST include at least one #### Scenario: block` → add a scenario

### Step 8 — Check status

```bash
openspec status --change <change-name>
```

Should show 4/4 artifacts complete: [x] proposal [x] design [x] specs [x] tasks

## Workflow: Implementing a Change

Once the proposal is validated:
1. Read `tasks.md` and execute tasks in order
2. After each task, run the verification step specified in the task
3. Check off completed tasks in `tasks.md`
4. After all tasks, run full verification: `pytest --tb=short -q`, `ruff check src/ tests/`, `mypy src/`
5. Run `openspec validate --all` to confirm specs still pass

## Workflow: Archiving a Completed Change

After implementation is complete and all tests/lint/types pass:

```bash
openspec archive <change-name>
```

This:
- Merges delta specs into the source-of-truth `openspec/specs/`
- Moves the change to `openspec/changes/archive/`
- Updates the spec history

After archiving, verify:
```bash
openspec validate --all
openspec list --specs
openspec list
```

`openspec list` should show no active changes (archived ones don't appear).

## Quick Reference — All Commands

| Command | When to use |
|---|---|
| `openspec list --specs` | See all source-of-truth specs and their requirement counts |
| `openspec list` | See all active (non-archived) change proposals |
| `openspec new change <name> --goal "..."` | Start a new change proposal |
| `openspec status --change <name>` | Check which artifacts (proposal/design/specs/tasks) are complete |
| `openspec validate <name>` | Validate a single change |
| `openspec validate --all` | Validate all specs and changes |
| `openspec validate --specs` | Validate only source-of-truth specs |
| `openspec validate --changes` | Validate only change proposals |
| `openspec show <name>` | Display a change or spec |
| `openspec archive <name>` | Archive a completed change into specs |
| `openspec context` | Print working context and OpenSpec root |
| `openspec instructions <artifact> --change <name>` | Get enriched instructions for writing an artifact |
| `openspec templates` | Show template file paths for all artifacts |
| `openspec schemas` | List available workflow schemas |

## Common Pitfalls

1. **Missing SHALL/MUST** — every requirement description must contain "SHALL" or "MUST". The validator enforces this strictly.
2. **Missing ## Purpose** — source-of-truth specs must start with `## Purpose` then `## Requirements`. Delta specs do NOT need Purpose (they start with `## ADDED/MODIFIED/REMOVED Requirements`).
3. **No scenarios** — every `### Requirement:` must have at least one `#### Scenario:` block with Given/When/Then.
4. **Wrong artifact order** — proposal must be completed before design and specs. Design and specs must be completed before tasks. The CLI blocks creating later artifacts if earlier ones are missing.
5. **Forgetting to validate** — always run `openspec validate --all` before committing OpenSpec files.
6. **Not reading config.yaml** — `openspec/config.yaml` contains project-specific rules that override the generic templates. Always read it first.
