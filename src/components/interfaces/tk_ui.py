"""Tkinter desktop UI for the Iraqi Legal Translation Agent.

Single responsibility (engineering-principles §1.1): render the desktop UI
and route button clicks to :func:`src.cli._translate_for_ui` — the testable
core that runs the streamed translation pipeline and returns the translation
text, provenance, and audit trace. The UI itself stays thin and untested by
CI (like the Gradio UI before it); all logic lives behind the
``_translate_for_ui`` seam which is unit-tested in ``tests/test_cli.py``.

Tabs (``ttk.Notebook``):
- **Translate** — source text box, direction dropdown, Translate button,
  translation output, and a provenance panel.
- **Audit Trace** — the full revision history (each draft + critique) for
  the last run.

The translation runs in a background ``threading.Thread`` so the UI stays
responsive during the (potentially slow) LLM call. Tkinter is not
thread-safe, so the worker thread writes results into a
``queue.Queue`` and the UI polls it via ``root.after``.
"""
from __future__ import annotations

import queue
import threading
import tkinter
from dataclasses import dataclass
from tkinter import DISABLED, NORMAL, Tk, messagebox, ttk
from typing import Any

from src.components.interfaces.cli import _new_run_logger
from src.components.interfaces.models import Adapters, UiTranslationResult
from src.components.interfaces.orchestration import (
    _audit_trace_markdown,
    _translate_for_ui,
)
from src.config import AppConfig


@dataclass(slots=True)
class UiWidgets:
    """Bundle of Tkinter widgets passed between build and event functions."""

    input_box: tkinter.Text
    direction_dd: ttk.Combobox
    btn: ttk.Button
    output_box: tkinter.Text
    prov_box: tkinter.Text
    trace_box: tkinter.Text


def _build_translate_tab(
    notebook: ttk.Notebook,
) -> tuple[tkinter.Text, ttk.Combobox, ttk.Button, tkinter.Text, tkinter.Text]:
    """Build the Translate tab; return (input, direction, button, output, provenance)."""
    frame: ttk.Frame = ttk.Frame(notebook, padding=10)
    notebook.add(frame, text="Translate")

    ttk.Label(frame, text="Source text:").pack(anchor="w")
    input_box: tkinter.Text = tkinter.Text(frame, height=8, wrap="word")
    input_box.pack(fill="x", pady=(0, 8))

    controls: ttk.Frame = ttk.Frame(frame)
    controls.pack(fill="x", pady=(0, 8))
    ttk.Label(controls, text="Direction:").pack(side="left")
    direction_dd: ttk.Combobox = ttk.Combobox(
        controls, values=["ar-en", "en-ar"], state="readonly", width=10
    )
    direction_dd.set("ar-en")
    direction_dd.pack(side="left", padx=(4, 0))
    btn: ttk.Button = ttk.Button(controls, text="Translate")
    btn.pack(side="right")

    ttk.Label(frame, text="Translation:").pack(anchor="w")
    output_box: tkinter.Text = tkinter.Text(frame, height=8, wrap="word")
    output_box.pack(fill="x", pady=(0, 8))

    prov_frame: ttk.LabelFrame = ttk.LabelFrame(frame, text="Provenance", padding=8)
    prov_frame.pack(fill="both", expand=True)
    prov_box: tkinter.Text = tkinter.Text(prov_frame, height=10, wrap="word")
    prov_box.pack(fill="both", expand=True)

    return input_box, direction_dd, btn, output_box, prov_box


def _build_trace_tab(notebook: ttk.Notebook) -> tkinter.Text:
    """Build the Audit Trace tab; return the trace text widget."""
    frame: ttk.Frame = ttk.Frame(notebook, padding=10)
    notebook.add(frame, text="Audit Trace")
    ttk.Label(
        frame,
        text="The full revision history (each draft + critique) for the last run.",
    ).pack(anchor="w", pady=(0, 8))
    trace_box: tkinter.Text = tkinter.Text(frame, wrap="word")
    trace_box.pack(fill="both", expand=True)
    trace_box.insert("1.0", _audit_trace_markdown([]))
    trace_box.config(state=DISABLED)
    return trace_box


def _start_translation(
    cfg: AppConfig,
    adapters: Adapters,
    widgets: UiWidgets,
    result_queue: queue.Queue[tuple[str, Any]],
) -> None:
    """Read UI inputs, disable the button, and start the worker thread."""
    input_text: str = widgets.input_box.get("1.0", "end-1c")
    direction: str = widgets.direction_dd.get()

    if not input_text.strip():
        messagebox.showwarning("Empty input", "Input text is empty.")
        return

    widgets.btn.config(state=DISABLED)
    widgets.output_box.delete("1.0", "end")
    widgets.output_box.insert("1.0", "Translating…")
    widgets.prov_box.delete("1.0", "end")
    widgets.trace_box.config(state=NORMAL)
    widgets.trace_box.delete("1.0", "end")
    widgets.trace_box.insert("1.0", "Translating…")
    widgets.trace_box.config(state=DISABLED)

    def _worker() -> None:
        """Run the translation off the UI thread; push result to queue."""
        try:
            result: UiTranslationResult = _translate_for_ui(
                input_text, direction, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index,
                persist_dir=adapters.persist_dir,
                run_logger=_new_run_logger(cfg),
                tm=adapters.tm,
            )
            result_queue.put(("ok", result))
        except Exception as e:  # noqa: BLE001 — UI must not crash
            result_queue.put(("error", str(e)))

    threading.Thread(target=_worker, daemon=True).start()


def _poll_result(root: Tk, widgets: UiWidgets, result_queue: queue.Queue[tuple[str, Any]]) -> None:
    """Poll the queue for a translation result; update UI if ready."""
    try:
        kind, payload = result_queue.get_nowait()
    except queue.Empty:
        root.after(200, _poll_result, root, widgets, result_queue)
        return

    widgets.btn.config(state=NORMAL)
    widgets.output_box.delete("1.0", "end")
    widgets.prov_box.delete("1.0", "end")
    widgets.trace_box.config(state=NORMAL)
    widgets.trace_box.delete("1.0", "end")

    if kind == "error":
        widgets.output_box.insert("1.0", f"Translation error: {payload}")
        widgets.trace_box.insert("1.0", _audit_trace_markdown([]))
    else:
        result: UiTranslationResult = payload
        widgets.output_box.insert("1.0", result.translation)
        widgets.prov_box.insert("1.0", result.provenance_md)
        widgets.trace_box.insert("1.0", result.audit_trace_md)

    widgets.trace_box.config(state=DISABLED)


def launch_ui(cfg: AppConfig, adapters: Adapters) -> None:
    """Build and run the Tkinter desktop UI.

    Called by the CLI ``ui`` command. ``cfg`` and ``adapters`` are
    constructed by the CLI (the only place concrete adapters are built,
    engineering-principles §3.6) and injected here.
    """
    root: Tk = Tk()
    root.title("Iraqi Legal Translation Agent")
    root.geometry("800x700")

    notebook: ttk.Notebook = ttk.Notebook(root)
    input_box, direction_dd, btn, output_box, prov_box = _build_translate_tab(notebook)
    trace_box: tkinter.Text = _build_trace_tab(notebook)
    notebook.pack(fill="both", expand=True)

    widgets: UiWidgets = UiWidgets(
        input_box=input_box, direction_dd=direction_dd, btn=btn,
        output_box=output_box, prov_box=prov_box, trace_box=trace_box,
    )
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue[tuple[str, Any]]()

    def _on_translate() -> None:
        """Button handler — start translation in a background thread."""
        _start_translation(cfg, adapters, widgets, result_queue)
        root.after(200, _poll_result, root, widgets, result_queue)

    btn.config(command=_on_translate)
    root.mainloop()
