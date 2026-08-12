## Purpose

The `UiBackend` protocol and its implementations (`web_ui`, `tk_ui`).
This capability exists so that the `ui` CLI command can select the
desktop UI backend from configuration (`cfg.ui.backend`) without
hard-importing a specific implementation, following the Open-Closed
Principle: adding a new backend (e.g., a Qt-based UI) is additive and
does not require editing `cli.py`.

## ADDED Requirements

### Requirement: UiBackend protocol

`src/components/interfaces/ui_backend.py` SHALL define a PEP 544 Protocol `UiBackend` with a `launch(cfg: AppConfig, adapters: Adapters) -> None` method. `web_ui.launch_ui` and `tk_ui.launch_ui` SHALL satisfy the protocol (structural subtyping). The `ui` CLI command SHALL select the backend from `cfg.ui.backend` (a `Literal["web", "tk"]` defaulting to `"web"`) and call its `launch` method; it SHALL NOT hard-import a specific implementation.

#### Scenario: web_ui.launch_ui satisfies UiBackend
- **GIVEN** the `web_ui.launch_ui` function
- **WHEN** it is checked against the `UiBackend` protocol
- **THEN** it satisfies the protocol (structural subtyping)

#### Scenario: tk_ui.launch_ui satisfies UiBackend
- **GIVEN** the `tk_ui.launch_ui` function
- **WHEN** it is checked against the `UiBackend` protocol
- **THEN** it satisfies the protocol (structural subtyping)

#### Scenario: ui command selects web backend by default
- **GIVEN** a `config.yaml` with no `ui:` section (or `ui.backend: web`)
- **WHEN** `iraqi-translate ui` runs
- **THEN** the pywebview desktop UI is launched (the web backend is selected)

#### Scenario: ui command selects tk backend when configured
- **GIVEN** a `config.yaml` with `ui.backend: tk`
- **WHEN** `iraqi-translate ui` runs
- **THEN** the Tkinter desktop UI is launched (the tk backend is selected)

#### Scenario: ui command does not hard-import a specific backend
- **GIVEN** the `commands/ui.py` source
- **WHEN** its imports are inspected
- **THEN** it imports the `UiBackend` protocol and selects the implementation via `cfg.ui.backend`; it does not contain `from src.components.interfaces.web_ui import launch_ui` at module top level (the import is deferred to the selection branch)
