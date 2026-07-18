"""pywebview-based desktop UI for the Iraqi Legal Translation Agent.

Single responsibility (engineering-principles §1.1): render a professional
web-based desktop UI and route translate button clicks to
:func:`src.cli._translate_for_ui` — the same testable core used by the
Tkinter UI. The UI itself stays thin and untested by CI; all logic lives
behind the ``_translate_for_ui`` seam which is unit-tested in
``tests/test_cli.py``.

The frontend is a single embedded HTML document with inline CSS and JS
(no external assets, no build step). pywebview renders it in a native
WebView2 (Windows) / WebKit (macOS/Linux) window. The Python ``Api``
class exposes methods that JS calls via ``pywebview.api.*``.

Features:
- **Translate tab** — source textarea, direction + model dropdowns,
  example sentences, Translate button (Ctrl+Enter), translation output
  with copy button, structured provenance panel, char/word count.
- **Audit Trace tab** — the full revision history (each draft + critique).
- **History tab** — last 10 translations with one-click reload.
- **Theme toggle** — dark/light switch with CSS custom properties.
- **Status bar** — live status indicator + data store counts.
"""
from __future__ import annotations

import logging
import os
import secrets
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import webview

from src.components.interfaces.cli import _new_run_logger, _resolve_path
from src.components.interfaces.diagnostics import _list_ollama_models
from src.components.interfaces.excel import translate_excel
from src.components.interfaces.models import Adapters, ExcelTranslationReport, UiTranslationResult
from src.components.interfaces.orchestration import (
    _audit_trace_markdown,
    _provenance_markdown,
    _translate_for_ui,
)
from src.components.interfaces.web_frontend import _HTML
from src.components.translation_pipeline.exceptions import (
    EmbeddingConnectionError,
    LegalTranslationError,
    OllamaConnectionError,
    RAMGuardError,
)
from src.components.translation_pipeline.models import TranslationState
from src.config import AppConfig

logger = logging.getLogger(__name__)

# Example legal sentences for the dropdown (covers different domains).
_EXAMPLES: list[dict[str, str]] = [
    {"label": "Court system", "text": "محكمة النقض هي أعلى هيئة قضائية في العراق"},
    {"label": "Civil procedure", "text": "وفقا للمادة السادسة من قانون أصول المحاكمات"
                                          " المدنية، تختص محكمة البداية بالنظر في الدعاوى المدنية"},
    {"label": "Contracts", "text": "عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن"},
    {"label": "Criminal law", "text": "الجريمة هي فعل يجرمه القانون ويعاقب عليه بعقوبة محددة"},
    {"label": "Rights", "text": "الحقوق الأساسية للأفراد مصونة بموجب الدستور والقانون"},
    {"label": "Treaties", "text": "الدول الأطراف في المعاهدة ملزمة بتنفيذ التزاماتها بحسن نية"},
    {"label": "Legal capacity", "text": "الأهلية هي صلاحية الشخص لاكتساب الحقوق وتحمل الالتزامات"},
]


@dataclass(slots=True)
class _PendingResult:
    """Holds a translation result pending pickup by the JS poller."""

    status: str  # "ok" | "error" | "idle" | "translating" | "review_pending"
    translation: str = ""
    provenance: str = ""
    audit_trace: str = ""
    error: str = ""


@dataclass(slots=True)
class _ExcelJob:
    """In-flight Excel translation job state (single-user, single-session).

    ``state`` is one of ``"running"``, ``"done"``, ``"cancelled"``,
    ``"error"``. ``report`` is the final :class:`ExcelTranslationReport` (or
    ``None`` while running). ``cancel_event`` is wired to
    :func:`translate_excel`'s ``cancel_event`` parameter.
    """

    job_id: str
    state: str = "running"
    completed: int = 0
    total: int = 0
    current: str = ""
    report: ExcelTranslationReport | None = None
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)


class _UiHumanReviewer:
    """Thread-safe human reviewer for the web UI.

    Implements :class:`src.hitl.HumanReviewer`. The ``review`` method blocks
    the worker thread until the JS frontend calls :meth:`submit_review` (or
    :meth:`approve_review`). Uses a :class:`threading.Event` for hand-off.
    """

    __slots__ = ("_draft", "_edited", "_event", "_lock")

    def __init__(self) -> None:
        self._draft: str = ""
        self._edited: str = ""
        self._event: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()

    def set_draft(self, draft: str) -> None:
        """Store the draft for the JS to display (called before review())."""
        with self._lock:
            self._draft = draft

    def review(self, state: TranslationState) -> str:
        """Block until the human submits or approves, then return the text."""
        self._event.wait()
        self._event.clear()
        with self._lock:
            return self._edited

    def submit_review(self, edited_text: str) -> None:
        """Human submitted an edited draft — unblock the worker thread."""
        with self._lock:
            self._edited = edited_text
        self._event.set()

    def approve_review(self) -> None:
        """Human approved the draft as-is — unblock with the original draft."""
        with self._lock:
            self._edited = self._draft
        self._event.set()


class _ApiContext:
    """Shared mutable state + dependencies for the API facades.

    The facades (:class:`TranslationApi`, :class:`ExcelApi`,
    :class:`SystemApi`) are split out of the original ``Api`` class for
    maintainability, but they share concurrency state (a single lock, the
    in-flight translation result, the Excel job slot, the reviewer, and the
    history log) because the JS-facing ``Api`` enforces concurrency = 1
    across *both* single-sentence and Excel runs. This context object holds
    that shared state so the facades stay focused without duplicating it.
    """

    __slots__ = ("cfg", "adapters", "models", "token", "lock", "result",
                 "history", "reviewer", "excel_job")

    def __init__(self, cfg: AppConfig, adapters: Adapters) -> None:
        self.cfg: AppConfig = cfg
        self.adapters: Adapters = adapters
        self.models: list[str] = _list_ollama_models(cfg.ollama_host)
        self.token: str = secrets.token_urlsafe(32)
        self.lock: threading.Lock = threading.Lock()
        self.result: _PendingResult = _PendingResult(status="idle")
        self.history: list[dict[str, str]] = []
        self.reviewer: _UiHumanReviewer | None = None
        self.excel_job: _ExcelJob | None = None

    def check_token(self, token: str) -> None:
        """Raise ``PermissionError`` if *token* does not match the session token."""
        if token != self.token:
            raise PermissionError("invalid or missing session token")


class SystemApi:
    """System/config facade: models, examples, and live store counts."""

    __slots__ = ("_ctx",)

    def __init__(self, ctx: _ApiContext) -> None:
        self._ctx: _ApiContext = ctx

    def get_models(self) -> list[str]:
        """Return available Ollama models, falling back to config default."""
        if self._ctx.models:
            return self._ctx.models
        return [self._ctx.cfg.llm_model]

    def get_default_model(self) -> str:
        """Return the default model (config value if available, else first)."""
        if self._ctx.cfg.llm_model in self._ctx.models:
            return self._ctx.cfg.llm_model
        if self._ctx.models:
            return self._ctx.models[0]
        return self._ctx.cfg.llm_model

    def get_examples(self) -> list[dict[str, str]]:
        """Return example legal sentences for the dropdown."""
        return _EXAMPLES

    def get_store_counts(self) -> dict[str, int]:
        """Return live counts for glossary, ChromaDB, and TM stores.

        Uses the existing embedder from adapters to construct a ChromaStore
        with the same settings as the pipeline — avoids the "instance already
        exists with different settings" error from creating a raw
        ``chromadb.PersistentClient`` with default settings.
        """
        counts: dict[str, int] = {"glossary": 0, "chroma": 0, "tm": 0}
        try:
            if self._ctx.adapters.glossary_index is not None:
                counts["glossary"] = len(self._ctx.adapters.glossary_index.terms)
        except Exception:  # noqa: BLE001
            pass
        try:
            from pathlib import Path

            from src.components.knowledge_sources.retrieval import ChromaStore

            persist = Path(self._ctx.adapters.persist_dir)
            if persist.exists():
                store = ChromaStore(
                    persist_dir=persist,
                    embedder=self._ctx.adapters.embedder,
                    cfg=self._ctx.cfg,
                )
                counts["chroma"] = store.count()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._ctx.adapters.tm is not None:
                counts["tm"] = len(self._ctx.adapters.tm.list_all())
        except Exception:  # noqa: BLE001
            pass
        return counts


class TranslationApi:
    """Translation workflow facade: async translate, review, history."""

    __slots__ = ("_ctx",)

    def __init__(self, ctx: _ApiContext) -> None:
        self._ctx: _ApiContext = ctx

    def get_history(self) -> list[dict[str, str]]:
        """Return the last 10 translations (input + direction + output)."""
        with self._ctx.lock:
            return list(self._ctx.history)

    def translate(self, token: str, input_text: str, direction: str, model: str) -> str:
        """Start a translation in a background thread. Returns 'started'."""
        self._ctx.check_token(token)
        if not input_text.strip():
            return "empty"
        with self._ctx.lock:
            # Concurrency = 1: refuse while an Excel run is in progress.
            if self._ctx.excel_job is not None and self._ctx.excel_job.state == "running":
                return "busy"
            self._ctx.result = _PendingResult(status="translating")

        # Override the configured model if the user selected a different one.
        effective_cfg: AppConfig = self._ctx.cfg
        if model and model != self._ctx.cfg.llm_model:
            effective_cfg = self._ctx.cfg.model_copy(update={"llm_model": model})

        # HITL: create a reviewer if hitl_enabled. The reviewer blocks the
        # worker thread at the review step; JS calls submit_review/approve_review
        # to unblock it. The reviewer signals via _PendingResult status.
        hitl_active: bool = effective_cfg.hitl_enabled
        if hitl_active:
            self._ctx.reviewer = _UiHumanReviewer()
        else:
            self._ctx.reviewer = None
        reviewer = self._ctx.reviewer

        def _worker() -> None:
            try:
                if hitl_active and reviewer is not None:
                    # Phase 1: run the graph WITHOUT the reviewer to get the
                    # draft, then signal JS to show the review panel.
                    from src.components.interfaces.orchestration import run_translation_streamed
                    from src.components.translation_pipeline.nodes import finalize_node

                    state, history = run_translation_streamed(
                        input_text, direction, effective_cfg,
                        llm=self._ctx.adapters.llm, embedder=self._ctx.adapters.embedder,
                        glossary_index=self._ctx.adapters.glossary_index,
                        persist_dir=self._ctx.adapters.persist_dir,
                        run_logger=_new_run_logger(self._ctx.cfg),
                        tm=self._ctx.adapters.tm,
                        reviewer=None,  # no HITL in phase 1
                    )
                    draft: str = state.get("draft", "")
                    reviewer.set_draft(draft)

                    # Signal JS: show the review panel with the draft.
                    with self._ctx.lock:
                        self._ctx.result = _PendingResult(
                            status="review_pending",
                            translation=draft,
                            provenance=_provenance_markdown(state),
                            audit_trace=_audit_trace_markdown(history),
                        )

                    # Phase 2: block until the human submits or approves.
                    from src.components.interfaces.hitl import human_review

                    reviewed: TranslationState = human_review(
                        state, effective_cfg,
                        llm=self._ctx.adapters.llm, reviewer=reviewer,
                        tm=self._ctx.adapters.tm,
                    )
                    if reviewed is not state:
                        reviewed = finalize_node(reviewed, cfg=effective_cfg)

                    result: UiTranslationResult = UiTranslationResult(
                        translation=reviewed.get("final_output") or "",
                        provenance_md=_provenance_markdown(reviewed),
                        audit_trace_md=_audit_trace_markdown(history),
                    )
                else:
                    result = _translate_for_ui(
                        input_text, direction, effective_cfg,
                        llm=self._ctx.adapters.llm, embedder=self._ctx.adapters.embedder,
                        glossary_index=self._ctx.adapters.glossary_index,
                        persist_dir=self._ctx.adapters.persist_dir,
                        run_logger=_new_run_logger(self._ctx.cfg),
                        tm=self._ctx.adapters.tm,
                    )
                with self._ctx.lock:
                    self._ctx.result = _PendingResult(
                        status="ok",
                        translation=result.translation,
                        provenance=result.provenance_md,
                        audit_trace=result.audit_trace_md,
                    )
                    # Append to history (keep last 10).
                    self._ctx.history.append({
                        "input": input_text[:200],
                        "direction": direction,
                        "translation": result.translation[:200],
                        "provenance": result.provenance_md[:500],
                        "audit_trace": result.audit_trace_md[:500],
                    })
                    if len(self._ctx.history) > 10:
                        self._ctx.history.pop(0)
            except Exception as e:  # noqa: BLE001 -- UI boundary: log + surface to user
                logger.exception("Api.translate failed")
                with self._ctx.lock:
                    self._ctx.result = _PendingResult(
                        status="error", error=str(e),
                        audit_trace=_audit_trace_markdown([]),
                    )

        threading.Thread(target=_worker, daemon=True).start()
        return "started"

    def submit_review(self, token: str, edited_text: str) -> str:
        """Human submitted an edited draft — unblock the worker thread."""
        self._ctx.check_token(token)
        if self._ctx.reviewer is not None:
            self._ctx.reviewer.submit_review(edited_text)
        return "submitted"

    def approve_review(self, token: str) -> str:
        """Human approved the draft as-is — unblock the worker thread."""
        self._ctx.check_token(token)
        if self._ctx.reviewer is not None:
            self._ctx.reviewer.approve_review()
        return "approved"


class ExcelApi:
    """Excel translation workflow facade: run, pick paths, status, cancel."""

    __slots__ = ("_ctx",)

    def __init__(self, ctx: _ApiContext) -> None:
        self._ctx: _ApiContext = ctx

    def pick_excel_input(self, token: str) -> str | None:
        """Open a native file dialog for ``.xlsx`` input; return the path or None."""
        self._ctx.check_token(token)
        if not webview.windows:
            return None
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG, file_types=("Excel Workbook (*.xlsx)",),
        )
        if not result:
            return None
        return result[0]

    def pick_excel_output(self, token: str, default_name: str) -> str | None:
        """Open a native save dialog for ``.xlsx`` output; return the path or None."""
        self._ctx.check_token(token)
        if not webview.windows:
            return None
        result = webview.windows[0].create_file_dialog(
            webview.SAVE_DIALOG, save_filename=default_name,
            file_types=("Excel Workbook (*.xlsx)",),
        )
        if not result:
            return None
        return result[0]

    def translate_excel(
        self,
        token: str,
        input_path: str,
        output_path: str,
        direction: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Start an Excel run in a background thread. Returns a job descriptor.

        Returns immediately with ``{"job_id": ..., "state": "running"}`` (or
        ``{"state": "error", "error": ...}`` if the run could not start). The
        result is delivered via :meth:`get_excel_status` polling.
        """
        self._ctx.check_token(token)
        # Validate input up front (no run started on invalid input).
        in_path = Path(input_path)
        if not in_path.is_file():
            return {"state": "error", "error": f"input file not found: {input_path}"}
        if in_path.suffix.lower() != ".xlsx":
            return {"state": "error", "error": f"input must be an .xlsx file, got: {in_path.suffix}"}
        if direction not in ("ar-en", "en-ar"):
            return {"state": "error", "error": f"invalid direction: {direction}"}

        with self._ctx.lock:
            # Concurrency = 1: refuse while a single-sentence run is in progress.
            if self._ctx.result.status == "translating":
                return {"state": "error", "error": "A translation is already in progress"}
            if self._ctx.excel_job is not None and self._ctx.excel_job.state == "running":
                return {"state": "error", "error": "An Excel run is already in progress"}
            job: _ExcelJob = _ExcelJob(job_id=uuid.uuid4().hex)
            self._ctx.excel_job = job

        # Apply option overrides to a deep copy of cfg (never mutate global cfg).
        base_cfg: AppConfig = self._ctx.cfg.model_copy(deep=True)
        excel_update: dict[str, Any] = {
            "translate_comments": bool(options.get("translate_comments", base_cfg.excel.translate_comments)),
            "translate_headers_footers": bool(options.get("translate_headers_footers", base_cfg.excel.translate_headers_footers)),
            "translate_chart_titles": bool(options.get("translate_chart_titles", base_cfg.excel.translate_chart_titles)),
            "max_segment_chars": int(options.get("max_segment_chars", base_cfg.excel.max_segment_chars)),
        }
        effective_cfg: AppConfig = base_cfg.model_copy(
            update={"excel": base_cfg.excel.model_copy(update=excel_update)}
        )

        def _worker() -> None:
            try:
                report = translate_excel(
                    input_path, output_path, direction, effective_cfg,
                    llm=self._ctx.adapters.llm, embedder=self._ctx.adapters.embedder,
                    glossary_index=self._ctx.adapters.glossary_index,
                    persist_dir=self._ctx.adapters.persist_dir,
                    run_logger=_new_run_logger(self._ctx.cfg),
                    tm=self._ctx.adapters.tm,
                    progress=_progress,
                    cancel_event=job.cancel_event,
                )
                with self._ctx.lock:
                    job.report = report
                    job.completed = report.total_segments
                    job.total = report.total_segments
                    job.current = ""
                    job.state = "cancelled" if report.cancelled else "done"
            except (OllamaConnectionError, EmbeddingConnectionError) as e:
                with self._ctx.lock:
                    job.state = "error"
                    job.error = (
                        f"Cannot reach the Ollama daemon: {e}\n"
                        "Is `ollama serve` running? Start it, then retry."
                    )
            except RAMGuardError as e:
                with self._ctx.lock:
                    job.state = "error"
                    job.error = (
                        f"RAM guard aborted the Excel run: {e}\n"
                        "Free up memory (close other applications) and retry."
                    )
            except LegalTranslationError as e:
                with self._ctx.lock:
                    job.state = "error"
                    job.error = str(e)
            except Exception as e:  # noqa: BLE001 -- UI boundary: log + surface to user
                logger.exception("Api.translate_excel failed")
                with self._ctx.lock:
                    job.state = "error"
                    job.error = f"excel error: {e}"

        def _progress(completed: int, total: int, current: str) -> None:
            with self._ctx.lock:
                job.completed = completed
                job.total = total
                job.current = current

        threading.Thread(target=_worker, daemon=True).start()
        return {"job_id": job.job_id, "state": "running"}

    def get_excel_status(self, job_id: str) -> dict[str, Any]:
        """Poll for the Excel job status. Called by JS every 300ms."""
        with self._ctx.lock:
            job: _ExcelJob | None = self._ctx.excel_job
            if job is None or job.job_id != job_id:
                return {"state": "error", "error": "unknown job"}
            report_dict: dict[str, Any] | None = None
            if job.report is not None:
                r = job.report
                report_dict = {
                    "total_segments": r.total_segments,
                    "translated": r.translated,
                    "skipped": r.skipped,
                    "failed": r.failed,
                    "cancelled": r.cancelled,
                    "warnings": list(r.warnings),
                }
            return {
                "state": job.state,
                "completed": job.completed,
                "total": job.total,
                "current": job.current,
                "report": report_dict,
                "error": job.error,
            }

    def cancel_excel(self, job_id: str) -> str:
        """Set the cancel event for the given Excel job."""
        with self._ctx.lock:
            job: _ExcelJob | None = self._ctx.excel_job
            if job is not None and job.job_id == job_id:
                job.cancel_event.set()
        return "cancelled"

    def open_in_explorer(self, token: str, path: str) -> str:
        """Open the OS file explorer with ``path`` selected (Windows)."""
        self._ctx.check_token(token)
        p: Path = Path(path)
        if not p.exists():
            return "missing"
        try:
            if os.name == "nt":  # Windows: select the file in Explorer.
                subprocess.Popen(  # noqa: S603 — explorer is a known OS binary
                    ["explorer", "/select,", str(p)],
                )
            else:  # Non-Windows fallback: open the parent directory.
                startfile = getattr(os, "startfile", None)
                if startfile is not None:
                    startfile(str(p.parent))
        except Exception as e:  # noqa: BLE001 -- UI boundary: log + surface to user
            logger.exception("Api.open_in_explorer failed")
            return f"error: {e}"
        return "ok"


class Api:
    """Python API exposed to the JS frontend via ``pywebview.api.*``.

    Thin facade that composes :class:`TranslationApi`, :class:`ExcelApi`, and
    :class:`SystemApi` and exposes the same JS-facing method names as the
    original monolithic ``Api``. Only this class is exposed to JS; the facades
    are internal implementation detail.

    Thread-safe: translation runs in a background thread; JS polls
    :meth:`get_result` until the status changes from "translating".

    Security: every state-mutating method requires a session token
    (generated at construction, injected into the page at load time).
    """

    __slots__ = ("_ctx", "_translation", "_excel", "_system")

    def __init__(self, cfg: AppConfig, adapters: Adapters) -> None:
        self._ctx: _ApiContext = _ApiContext(cfg, adapters)
        self._translation: TranslationApi = TranslationApi(self._ctx)
        self._excel: ExcelApi = ExcelApi(self._ctx)
        self._system: SystemApi = SystemApi(self._ctx)

    @property
    def _lock(self) -> threading.Lock:
        """Shared concurrency lock (exposed for backward compatibility)."""
        return self._ctx.lock

    @property
    def _result(self) -> _PendingResult:
        """Current pending translation result (exposed for backward compatibility)."""
        return self._ctx.result

    def get_token(self) -> str:
        """Return the session token (called once at page load)."""
        return self._ctx.token

    def _check_token(self, token: str) -> None:
        """Raise ``PermissionError`` if *token* does not match the session token."""
        self._ctx.check_token(token)

    # -- System facade -------------------------------------------------

    def get_models(self) -> list[str]:
        """Return available Ollama models, falling back to config default."""
        return self._system.get_models()

    def get_default_model(self) -> str:
        """Return the default model (config value if available, else first)."""
        return self._system.get_default_model()

    def get_examples(self) -> list[dict[str, str]]:
        """Return example legal sentences for the dropdown."""
        return self._system.get_examples()

    def get_store_counts(self) -> dict[str, int]:
        """Return live counts for glossary, ChromaDB, and TM stores."""
        return self._system.get_store_counts()

    # -- Translation facade --------------------------------------------

    def get_history(self) -> list[dict[str, str]]:
        """Return the last 10 translations (input + direction + output)."""
        return self._translation.get_history()

    def translate(self, token: str, input_text: str, direction: str, model: str) -> str:
        """Start a translation in a background thread. Returns 'started'."""
        return self._translation.translate(token, input_text, direction, model)

    def submit_review(self, token: str, edited_text: str) -> str:
        """Human submitted an edited draft — unblock the worker thread."""
        return self._translation.submit_review(token, edited_text)

    def approve_review(self, token: str) -> str:
        """Human approved the draft as-is — unblock the worker thread."""
        return self._translation.approve_review(token)

    def get_result(self) -> dict[str, str]:
        """Poll for the translation result. Called by JS every 300ms."""
        with self._ctx.lock:
            r: _PendingResult = self._ctx.result
        return {
            "status": r.status,
            "translation": r.translation,
            "provenance": r.provenance,
            "audit_trace": r.audit_trace,
            "error": r.error,
        }

    # -- Excel facade --------------------------------------------------

    def translate_excel(
        self,
        token: str,
        input_path: str,
        output_path: str,
        direction: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Start an Excel run in a background thread. Returns a job descriptor."""
        return self._excel.translate_excel(token, input_path, output_path, direction, options)

    def pick_excel_input(self, token: str) -> str | None:
        """Open a native file dialog for ``.xlsx`` input; return the path or None."""
        return self._excel.pick_excel_input(token)

    def pick_excel_output(self, token: str, default_name: str) -> str | None:
        """Open a native save dialog for ``.xlsx`` output; return the path or None."""
        return self._excel.pick_excel_output(token, default_name)

    def get_excel_status(self, job_id: str) -> dict[str, Any]:
        """Poll for the Excel job status. Called by JS every 300ms."""
        return self._excel.get_excel_status(job_id)

    def cancel_excel(self, job_id: str) -> str:
        """Set the cancel event for the given Excel job."""
        return self._excel.cancel_excel(job_id)

    def open_in_explorer(self, token: str, path: str) -> str:
        """Open the OS file explorer with ``path`` selected (Windows)."""
        return self._excel.open_in_explorer(token, path)

    def get_excel_options(self) -> dict[str, Any]:
        """Return the current ``cfg.excel`` values for the UI toggles."""
        ex = self._ctx.cfg.excel
        return {
            "translate_comments": ex.translate_comments,
            "translate_headers_footers": ex.translate_headers_footers,
            "translate_chart_titles": ex.translate_chart_titles,
            "max_segment_chars": ex.max_segment_chars,
        }

    # -- Cross-cutting helpers -----------------------------------------

    def is_busy(self) -> bool:
        """Return True if a single-sentence or Excel run is in progress."""
        with self._ctx.lock:
            if self._ctx.result.status == "translating":
                return True
            return self._ctx.excel_job is not None and self._ctx.excel_job.state == "running"

    def path_exists(self, path: str) -> bool:
        """Return True if ``path`` exists on disk (for overwrite confirmation)."""
        return Path(path).exists()





def launch_ui(cfg: AppConfig, adapters: Adapters) -> None:
    """Build and run the pywebview desktop UI.

    Called by the CLI ``ui`` command. ``cfg`` and ``adapters`` are
    constructed by the CLI (the only place concrete adapters are built,
    engineering-principles §3.6) and injected here.
    """
    from src.utils.logging_setup import configure_logging

    configure_logging(log_dir=_resolve_path(cfg, "logs"))
    api: Api = Api(cfg, adapters)
    window = webview.create_window(
        title="Iraqi Legal Translation Agent",
        html=_HTML,
        js_api=api,
        width=960,
        height=800,
        min_size=(750, 600),
        text_select=True,
    )

    def _inject_token() -> None:
        """Inject the session token into the page once it has loaded."""
        token: str = api.get_token()
        if window is not None:
            window.evaluate_js(f"window.__SESSION_TOKEN='{token}';")

    webview.start(func=_inject_token)

    # Clean up resources after the window closes (task 6.5).
    _close_adapters(adapters)


def _close_adapters(adapters: Adapters) -> None:
    """Close all resource-owning adapters (LLM, embedder, TM)."""
    llm_close = getattr(adapters.llm, "close", None)
    if callable(llm_close):
        llm_close()
    embedder_close = getattr(adapters.embedder, "close", None)
    if callable(embedder_close):
        embedder_close()
    if adapters.tm is not None:
        adapters.tm.close()
