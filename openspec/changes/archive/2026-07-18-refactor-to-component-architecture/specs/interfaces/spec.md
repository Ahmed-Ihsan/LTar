## ADDED Requirements

### Requirement: Interfaces component folder

The interface layer SHALL reside in `src/components/interfaces/` as a bounded-context component. The folder SHALL contain: `__init__.py` (re-exports), `models.py`, `cli.py`, `web_ui.py`, `tk_ui.py`, `mcp_server.py`, and `hitl.py`.

#### Scenario: Component folder structure
- **GIVEN** the refactored project structure
- **WHEN** the `src/components/interfaces/` directory is inspected
- **THEN** it contains `__init__.py`, `models.py`, `cli.py`, `web_ui.py`, `tk_ui.py`, `mcp_server.py`, and `hitl.py`

### Requirement: Interfaces models module

Interface-specific data models SHALL reside in `src/components/interfaces/models.py`. This includes `CheckResult` (doctor check outcome), `Adapters` (bundle of concrete adapters), and `UiTranslationResult` (translation result for UI consumption).

#### Scenario: Import interface models from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.models import CheckResult, Adapters, UiTranslationResult` is executed
- **THEN** all data classes are imported successfully

### Requirement: Interfaces CLI module

The Typer `app` and all CLI commands (`doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, `ui`) and helper functions SHALL reside in `src/components/interfaces/cli.py`.

#### Scenario: Import CLI app from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.cli import app` is executed
- **THEN** the Typer app is imported successfully

### Requirement: Interfaces web UI module

`launch_ui`, `Api`, and `_UiHumanReviewer` SHALL reside in `src/components/interfaces/web_ui.py`.

#### Scenario: Import web UI from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.web_ui import launch_ui` is executed
- **THEN** launch_ui is imported successfully

### Requirement: Interfaces Tkinter UI module

`launch_ui`, `UiWidgets`, and the Tkinter UI builder functions SHALL reside in `src/components/interfaces/tk_ui.py`.

#### Scenario: Import Tkinter UI from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.tk_ui import launch_ui` is executed
- **THEN** launch_ui is imported successfully

### Requirement: Interfaces MCP server module

The FastMCP `mcp` instance, all MCP tools (`search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library`, `search_all`), and `main()` SHALL reside in `src/components/interfaces/mcp_server.py`.

#### Scenario: Import MCP server from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.mcp_server import mcp, main` is executed
- **THEN** both the mcp instance and main function are imported successfully

### Requirement: Interfaces HITL module

`HumanReviewer` (Protocol), `human_review`, `_save_correction`, and `_save_to_tm` SHALL reside in `src/components/interfaces/hitl.py`.

#### Scenario: Import HITL API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.hitl import HumanReviewer, human_review` is executed
- **THEN** both the Protocol and the function are imported successfully

### Requirement: Interfaces public API re-export

`src/components/interfaces/__init__.py` SHALL re-export the component's public API so that `from src.components.interfaces import app, launch_ui, human_review` works without specifying the submodule.

#### Scenario: Re-exported public API
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces import app, human_review` is executed
- **THEN** all symbols are imported successfully via the package __init__

### Requirement: Interfaces inter-component imports

Modules within `interfaces/` SHALL import from other components using component paths (e.g., `from src.components.translation_pipeline.graph import build_graph`), not from the old flat `src.graph` paths.

#### Scenario: cli.py imports from translation pipeline component
- **GIVEN** the refactored cli.py
- **WHEN** its imports are inspected
- **THEN** it imports build_graph from `src.components.translation_pipeline.graph`, not from `src.graph`

#### Scenario: cli.py imports from infrastructure component
- **GIVEN** the refactored cli.py
- **WHEN** its imports are inspected
- **THEN** it imports RunLogger from `src.components.infrastructure.run_logging`, not from `src.run_logging`

#### Scenario: hitl.py imports from translation pipeline component
- **GIVEN** the refactored hitl.py
- **WHEN** its imports are inspected
- **THEN** it imports audit_node from `src.components.translation_pipeline.nodes`, not from `src.nodes`
