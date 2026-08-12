## MODIFIED Requirements

### Requirement: pywebview desktop UI

`launch_ui(cfg, adapters) -> None` SHALL build and run a pywebview window with an embedded HTML/CSS/JS frontend. An `Api` class is exposed to JS with methods: `get_models`, `get_default_model`, `get_examples`, `get_store_counts`, `get_history`, `translate`, `submit_review`, `approve_review`. A `_UiHumanReviewer` implements the HumanReviewer protocol thread-safely. `launch_ui` SHALL call `configure_logging(log_dir=cfg.paths.log_dir)` before building the window so UI-session errors are captured to `app.log`. Every `Api` method that catches `Exception` at the UI boundary (so the UI does not crash) SHALL log the exception via `logging.getLogger(__name__).exception(...)` before surfacing the error to JS — silent swallowing without a log line is forbidden.

#### Scenario: Web UI translate returns a result
- **GIVEN** the web UI Api is initialized with cfg and adapters
- **WHEN** api.translate("المادة ١", "ar-en", "qwen2.5:7b-instruct-q5_K_M") is called
- **THEN** a result string is returned containing the translation, provenance, and audit trace

#### Scenario: Web UI human review is thread-safe
- **GIVEN** the _UiHumanReviewer is used from the UI thread
- **WHEN** a review is submitted from the JS frontend
- **THEN** the review result is safely communicated back to the translation thread

#### Scenario: a UI-boundary exception is logged before surfacing
- **GIVEN** an `Api.translate` call whose underlying pipeline raises `RuntimeError("boom")`
- **WHEN** the `Api.translate` `except Exception as e:` block runs
- **THEN** `logger.exception("Api.translate failed")` is called (emitting a full traceback to `app.log`) BEFORE the error string is returned to JS, and the UI does not crash

#### Scenario: launch_ui configures logging on startup
- **GIVEN** `launch_ui` is called with a valid `cfg.paths.log_dir`
- **WHEN** the window is being built
- **THEN** `configure_logging(log_dir=cfg.paths.log_dir)` has been called and `app.log` is being written

### Requirement: Tkinter desktop UI

`launch_ui(cfg, adapters) -> None` SHALL build and run a Tkinter window with a tabbed notebook (Translate tab + Audit Trace tab). Translation runs in a background thread; results are polled via a queue. `UiWidgets` bundles the input_box, direction dropdown, translate button, output box, provenance box, and trace box. `launch_ui` SHALL call `configure_logging(log_dir=cfg.paths.log_dir)` before building the window. The background-thread worker SHALL catch `Exception` (so the UI does not crash) but SHALL log the exception via `logging.getLogger(__name__).exception(...)` before putting the error on the result queue — silent swallowing without a log line is forbidden.

#### Scenario: Tkinter UI launches with tabs
- **GIVEN** a valid cfg and adapters
- **WHEN** launch_ui is called
- **THEN** a Tkinter window opens with a "Translate" tab and an "Audit Trace" tab

#### Scenario: Translation runs in background thread
- **GIVEN** the user clicks the Translate button in the Tkinter UI
- **WHEN** _start_translation is called
- **THEN** the translation runs in a background thread and the UI remains responsive, with results polled via _poll_result

#### Scenario: a worker-thread exception is logged before surfacing
- **GIVEN** a background-thread translation that raises `RuntimeError("boom")`
- **WHEN** the worker's `except Exception as e:` block runs
- **THEN** `logger.exception("Tk translation worker failed")` is called (emitting a full traceback to `app.log`) BEFORE `result_queue.put(("error", str(e)))`, and the UI does not crash

#### Scenario: launch_ui configures logging on startup
- **GIVEN** `launch_ui` is called with a valid `cfg.paths.log_dir`
- **WHEN** the window is being built
- **THEN** `configure_logging(log_dir=cfg.paths.log_dir)` has been called and `app.log` is being written
