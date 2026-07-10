## MODIFIED Requirements

### Requirement: CLI subcommands

The CLI SHALL be a Typer application with eight subcommands: `doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, and `ui`. Each command accepts its arguments via Typer options and arguments. All `dict`, `list`, and other generic type annotations in cli.py SHALL include type parameters (e.g., `dict[str, object]` not bare `dict`, `list[str]` not bare `list`). The `_initial_state` function SHALL construct a `TranslationState` with all required keys including `tm_hits` and `web_search_results`. The `direction` field assignment SHALL use a `Direction` literal cast or the existing `# type: ignore[arg-type]` comment SHALL be kept only if mypy still flags it. Variables typed as `object` that are known to be concrete types at runtime (e.g., ChromaDB stores, file handles) SHALL be annotated with their concrete types. Stale `# type: ignore` comments SHALL be removed. The `_canonical_model_name` function SHALL handle `str | None` input by defaulting to an empty string or asserting non-None before use. The `int(ByteSize | None)` call SHALL guard against `None` before conversion.

#### Scenario: doctor runs environment diagnostics
- **GIVEN** the CLI is invoked with the `doctor` subcommand
- **WHEN** the command executes
- **THEN** it checks Ollama reachability, model presence, ChromaDB directory, glossary DB, TM DB, and RAM headroom, printing a CheckResult for each

#### Scenario: translate translates a single text
- **GIVEN** the CLI is invoked with `translate --input "المادة ١" --direction ar-en`
- **WHEN** the command executes
- **THEN** the translation pipeline runs and the final translation is printed

#### Scenario: batch translates a JSONL file sequentially
- **GIVEN** the CLI is invoked with `batch --input translations.jsonl`
- **WHEN** the command executes
- **THEN** each line of the JSONL file is translated sequentially (concurrency = 1) and results are written to the output file

#### Scenario: ingest builds the vector store and glossary
- **GIVEN** the CLI is invoked with `ingest --rebuild`
- **WHEN** the command executes
- **THEN** the corpus is parsed, chunked, embedded, and written to ChromaDB, and the glossary is loaded into SQLite

#### Scenario: tm-build builds TM from corpus
- **GIVEN** the CLI is invoked with `tm-build`
- **WHEN** the command executes
- **THEN** the Translation Memory is built from aligned corpus files

#### Scenario: ui launches the web-based desktop UI
- **GIVEN** the CLI is invoked with `ui`
- **WHEN** the command executes
- **THEN** the pywebview desktop UI is launched

#### Scenario: _initial_state includes all required TypedDict keys
- **GIVEN** the refactored _initial_state function
- **WHEN** it is called with input_text and direction
- **THEN** the returned dict includes tm_hits=[] and web_search_results=[] in addition to all other required TranslationState keys

#### Scenario: cli.py passes mypy strict
- **GIVEN** the refactored cli.py with type parameters, concrete types, and complete TypedDict construction
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for cli.py (no type-arg, no typeddict-item, no attr-defined, no unused-ignore)

### Requirement: CLI dependency injection

The CLI SHALL construct concrete adapters via `_construct_adapters(cfg) -> Adapters`, which bundles `llm`, `embedder`, `glossary_index`, `persist_dir`, and `tm`. `_run_translation` and `_run_translation_streamed` accept these as keyword-only args for dependency injection (DIP). Variables holding adapter instances or store handles SHALL be annotated with concrete types (e.g., `ChromaStore`, `TranslationMemory`) not `object`, so that method calls like `.close()` and `.list_all()` pass mypy strict.

#### Scenario: Adapters bundle contains all concrete adapters
- **GIVEN** a valid AppConfig
- **WHEN** _construct_adapters is called
- **THEN** an Adapters object is returned with llm, embedder, glossary_index, persist_dir, and tm fields

#### Scenario: Adapter variables have concrete types
- **GIVEN** the refactored cli.py with concrete type annotations
- **WHEN** mypy checks method calls on adapter variables (e.g., store.close(), tm.list_all())
- **THEN** no attr-defined errors are reported because the variables are typed with their concrete classes

### Requirement: CLI helper functions

The CLI SHALL provide helper functions: `_project_root`, `_resolve_path`, `_new_run_logger`, `_new_tm`, `_check_ollama_reachable`, `_canonical_model_name`, `_list_ollama_models`, `_check_models_present`, `_check_chroma_dir`, `_check_glossary_db`, `_check_tm_db`, `_check_ram_headroom`, `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`. The `_canonical_model_name` helper SHALL accept `str | None` and return `str` by handling the `None` case internally. The `int()` conversion of `ByteSize | None` SHALL guard against `None`. The `str`-to-`int` assignment conflict SHALL be resolved by using the correct type for the variable.

#### Scenario: Provenance markdown is generated
- **GIVEN** a TranslationState with glossary_hits, context_chunks, and tm_hits
- **WHEN** _provenance_markdown is called
- **THEN** a markdown string documenting the sources used is returned

#### Scenario: Audit trace markdown is generated
- **GIVEN** a list of revision states from the audit loop
- **WHEN** _audit_trace_markdown is called
- **THEN** a markdown string documenting each revision pass is returned

#### Scenario: _canonical_model_name handles None
- **GIVEN** a model name that is None
- **WHEN** _canonical_model_name is called
- **THEN** it returns a default string (e.g., "") without raising a mypy arg-type error

### Requirement: pywebview desktop UI

`launch_ui(cfg, adapters) -> None` SHALL build and run a pywebview window with an embedded HTML/CSS/JS frontend. An `Api` class is exposed to JS with methods: `get_models`, `get_default_model`, `get_examples`, `get_store_counts`, `get_history`, `translate`, `submit_review`, `approve_review`. A `_UiHumanReviewer` implements the HumanReviewer protocol thread-safely. All `dict` annotations in web_ui.py SHALL include type parameters. The `embedder` argument to `ChromaStore` SHALL be typed as `EmbeddingAdapter | None` not `object`. The `list_all()` call on the TM/glossary SHALL use a variable typed as `TranslationMemory` or `GlossaryIndex` not `object`. Stale `# type: ignore` comments SHALL be removed.

#### Scenario: Web UI translate returns a result
- **GIVEN** the web UI Api is initialized with cfg and adapters
- **WHEN** api.translate("المادة ١", "ar-en", "qwen2.5:7b-instruct-q5_K_M") is called
- **THEN** a result string is returned containing the translation, provenance, and audit trace

#### Scenario: Web UI human review is thread-safe
- **GIVEN** the _UiHumanReviewer is used from the UI thread
- **WHEN** a review is submitted from the JS frontend
- **THEN** the review result is safely communicated back to the translation thread

#### Scenario: web_ui.py passes mypy strict
- **GIVEN** the refactored web_ui.py with type parameters and concrete types
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for web_ui.py (no type-arg, no arg-type, no attr-defined, no unused-ignore)

### Requirement: Tkinter desktop UI

`launch_ui(cfg, adapters) -> None` SHALL build and run a Tkinter window with a tabbed notebook (Translate tab + Audit Trace tab). Translation runs in a background thread; results are polled via a queue. `UiWidgets` bundles the input_box, direction dropdown, translate button, output box, provenance box, and trace box. The `ttk.Text` type references SHALL be resolved — either by using `tkinter.Text` (which has stubs) instead of `ttk.Text` (which does not exist in ttk), or by using `Any` with a `# type: ignore[name-defined]` comment where the widget type is genuinely not in stubs. All `Queue` annotations SHALL include type parameters (e.g., `Queue[UiTranslationResult | None]`). Stale `# type: ignore` comments SHALL be removed.

#### Scenario: Tkinter UI launches with tabs
- **GIVEN** a valid cfg and adapters
- **WHEN** launch_ui is called
- **THEN** a Tkinter window opens with a "Translate" tab and an "Audit Trace" tab

#### Scenario: Translation runs in background thread
- **GIVEN** the user clicks the Translate button in the Tkinter UI
- **WHEN** _start_translation is called
- **THEN** the translation runs in a background thread and the UI remains responsive, with results polled via _poll_result

#### Scenario: tk_ui.py passes mypy strict
- **GIVEN** the refactored tk_ui.py with ttk.Text fixed and Queue type parameters
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for tk_ui.py (no name-defined, no attr-defined, no type-arg, no unused-ignore)

### Requirement: Human-in-the-loop review

`HumanReviewer` SHALL be a PEP 544 Protocol with a `review(state) -> str` method. `human_review(state, cfg, *, llm, reviewer, tm) -> TranslationState` runs the human review step: if the reviewer edits the draft, the correction is saved and re-audited. `_save_correction` writes corrections to a JSONL file. `_save_to_tm` inserts corrected pairs into the Translation Memory. The `record` dict in `_save_correction` SHALL be typed as `dict[str, object]` not bare `dict`.

#### Scenario: Reviewer approves without edits
- **GIVEN** a HumanReviewer that returns the original draft unchanged
- **WHEN** human_review is called
- **THEN** the state is returned with final_output set and no re-audit occurs

#### Scenario: Reviewer edits the draft
- **GIVEN** a HumanReviewer that returns an edited draft different from the original
- **WHEN** human_review is called
- **THEN** the correction is saved via _save_correction, the edited draft is re-audited via audit_node, and the state is updated

#### Scenario: Corrected pair is saved to TM
- **GIVEN** a reviewer edits the draft and a TranslationMemory is provided
- **WHEN** human_review is called
- **THEN** _save_to_tm inserts the corrected source-target pair into the TM

#### Scenario: hitl.py passes mypy strict
- **GIVEN** the refactored hitl.py with dict type parameter
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for hitl.py (no type-arg)
