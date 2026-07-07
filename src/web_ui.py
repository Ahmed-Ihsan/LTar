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

import threading
from dataclasses import dataclass

import webview

from src.cli import (
    Adapters,
    UiTranslationResult,
    _audit_trace_markdown,
    _list_ollama_models,
    _new_run_logger,
    _translate_for_ui,
)
from src.config import AppConfig

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

    status: str  # "ok" | "error" | "idle" | "translating"
    translation: str = ""
    provenance: str = ""
    audit_trace: str = ""
    error: str = ""


class Api:
    """Python API exposed to the JS frontend via ``pywebview.api.*``.

    Thread-safe: translation runs in a background thread; JS polls
    :meth:`get_result` until the status changes from "translating".
    """

    __slots__ = ("_cfg", "_adapters", "_models", "_result", "_lock", "_history")

    def __init__(self, cfg: AppConfig, adapters: Adapters) -> None:
        self._cfg: AppConfig = cfg
        self._adapters: Adapters = adapters
        self._models: list[str] = _list_ollama_models(cfg.ollama_host)
        self._result: _PendingResult = _PendingResult(status="idle")
        self._lock: threading.Lock = threading.Lock()
        self._history: list[dict] = []

    def get_models(self) -> list[str]:
        """Return available Ollama models, falling back to config default."""
        if self._models:
            return self._models
        return [self._cfg.llm_model]

    def get_default_model(self) -> str:
        """Return the default model (config value if available, else first)."""
        if self._cfg.llm_model in self._models:
            return self._cfg.llm_model
        if self._models:
            return self._models[0]
        return self._cfg.llm_model

    def get_examples(self) -> list[dict]:
        """Return example legal sentences for the dropdown."""
        return _EXAMPLES

    def get_store_counts(self) -> dict:
        """Return live counts for glossary, ChromaDB, and TM stores.

        Uses the existing embedder from adapters to construct a ChromaStore
        with the same settings as the pipeline — avoids the "instance already
        exists with different settings" error from creating a raw
        ``chromadb.PersistentClient`` with default settings.
        """
        counts: dict = {"glossary": 0, "chroma": 0, "tm": 0}
        try:
            if self._adapters.glossary_index is not None:
                counts["glossary"] = len(self._adapters.glossary_index.terms)
        except Exception:  # noqa: BLE001
            pass
        try:
            from pathlib import Path

            from src.retrieval import ChromaStore

            persist = Path(self._adapters.persist_dir)
            if persist.exists():
                store = ChromaStore(
                    persist_dir=persist,
                    embedder=self._adapters.embedder,
                    cfg=self._cfg,
                )
                counts["chroma"] = store.count()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._adapters.tm is not None:
                counts["tm"] = len(self._adapters.tm.list_all())
        except Exception:  # noqa: BLE001
            pass
        return counts

    def get_history(self) -> list[dict]:
        """Return the last 10 translations (input + direction + output)."""
        with self._lock:
            return list(self._history)

    def translate(self, input_text: str, direction: str, model: str) -> str:
        """Start a translation in a background thread. Returns 'started'."""
        if not input_text.strip():
            return "empty"
        with self._lock:
            self._result = _PendingResult(status="translating")

        # Override the configured model if the user selected a different one.
        effective_cfg: AppConfig = self._cfg
        if model and model != self._cfg.llm_model:
            effective_cfg = self._cfg.model_copy(update={"llm_model": model})

        def _worker() -> None:
            try:
                result: UiTranslationResult = _translate_for_ui(
                    input_text, direction, effective_cfg,
                    llm=self._adapters.llm, embedder=self._adapters.embedder,
                    glossary_index=self._adapters.glossary_index,
                    persist_dir=self._adapters.persist_dir,
                    run_logger=_new_run_logger(self._cfg),
                    tm=self._adapters.tm,
                )
                with self._lock:
                    self._result = _PendingResult(
                        status="ok",
                        translation=result.translation,
                        provenance=result.provenance_md,
                        audit_trace=result.audit_trace_md,
                    )
                    # Append to history (keep last 10).
                    self._history.append({
                        "input": input_text[:200],
                        "direction": direction,
                        "translation": result.translation[:200],
                        "provenance": result.provenance_md[:500],
                        "audit_trace": result.audit_trace_md[:500],
                    })
                    if len(self._history) > 10:
                        self._history.pop(0)
            except Exception as e:  # noqa: BLE001 — UI must not crash
                with self._lock:
                    self._result = _PendingResult(
                        status="error", error=str(e),
                        audit_trace=_audit_trace_markdown([]),
                    )

        threading.Thread(target=_worker, daemon=True).start()
        return "started"

    def get_result(self) -> dict:
        """Poll for the translation result. Called by JS every 300ms."""
        with self._lock:
            r: _PendingResult = self._result
        return {
            "status": r.status,
            "translation": r.translation,
            "provenance": r.provenance,
            "audit_trace": r.audit_trace,
            "error": r.error,
        }


# ---------------------------------------------------------------------------
# Frontend — single embedded HTML document (no external assets)
# ---------------------------------------------------------------------------

_HTML: str = r"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Iraqi Legal Translation Agent</title>
<style>
/* ── Design tokens ──────────────────────────────────────────────── */
:root {
  /* Neutral surfaces (dark, layered elevation) */
  --bg:        #0b0d13;
  --surface:   #14171f;
  --surface2:  #1b1f2a;
  --surface3:  #232838;
  --surface4:  #2c3245;
  --border:    #2a2f3e;
  --border-2:  #353c50;

  /* Text */
  --text:      #e6e8ee;
  --text-dim:  #9aa0b0;
  --text-mute: #6b7185;

  /* Brand + semantic */
  --accent:        #5b9bFF;
  --accent-hover:  #4a8aef;
  --accent-soft:   rgba(91,155,255,0.14);
  --accent-ring:   rgba(91,155,255,0.40);
  --success:       #34d399;
  --error:         #f87171;
  --warn:          #fbbf24;
  --grad:          linear-gradient(135deg, #5b9bFF 0%, #8b7bff 100%);

  /* Elevation shadows */
  --shadow-xs: 0 1px 2px rgba(0,0,0,0.20);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.28), 0 1px 2px rgba(0,0,0,0.20);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.32), 0 2px 4px rgba(0,0,0,0.20);
  --shadow-lg: 0 12px 32px rgba(0,0,0,0.40), 0 4px 8px rgba(0,0,0,0.24);

  /* Radii */
  --r-xs: 4px;
  --r-sm: 6px;
  --r-md: 8px;
  --r-lg: 12px;

  /* Spacing scale */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 20px; --sp-6: 24px; --sp-8: 32px;

  /* Type */
  --font-ui:  'Segoe UI', system-ui, -apple-system, 'Cairo', 'Tajawal', sans-serif;
  --font-mono:'Cascadia Code','Consolas','SF Mono',ui-monospace,monospace;
  --fs-xs:  11px; --fs-sm: 12px; --fs-md: 13px; --fs-base: 14px; --fs-lg: 15px;
  --lh-tight: 1.35; --lh-base: 1.6;
}
[data-theme="light"] {
  --bg:        #f4f6fb;
  --surface:   #ffffff;
  --surface2:  #f1f3f8;
  --surface3:  #e9ecf4;
  --surface4:  #dde2ee;
  --border:    #dce0ea;
  --border-2:  #c8cfde;
  --text:      #1a1d28;
  --text-dim:  #5c6276;
  --text-mute: #8a90a3;
  --accent:        #2563eb;
  --accent-hover:  #1d4ed8;
  --accent-soft:   rgba(37,99,235,0.10);
  --accent-ring:   rgba(37,99,235,0.32);
  --success:       #059669;
  --error:         #dc2626;
  --warn:          #d97706;
  --grad:          linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
  --shadow-xs: 0 1px 2px rgba(16,24,40,0.06);
  --shadow-sm: 0 1px 3px rgba(16,24,40,0.08), 0 1px 2px rgba(16,24,40,0.05);
  --shadow-md: 0 4px 12px rgba(16,24,40,0.10), 0 2px 4px rgba(16,24,40,0.06);
  --shadow-lg: 0 12px 32px rgba(16,24,40,0.14), 0 4px 8px rgba(16,24,40,0.08);
}

/* ── Base ───────────────────────────────────────────────────────── */
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  font-family: var(--font-ui);
  font-size: var(--fs-base);
  line-height: var(--lh-base);
  background: var(--bg);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
::selection { background: var(--accent-soft); }

/* Scrollbar */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--border-2); border-radius: 8px;
  border: 2px solid transparent; background-clip: padding-box;
}
::-webkit-scrollbar-thumb:hover { background: var(--text-mute); background-clip: padding-box; }

/* ── Header ─────────────────────────────────────────────────────── */
.header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
  padding: var(--sp-3) var(--sp-5);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-shrink: 0;
}
.header-logo {
  width: 38px; height: 38px;
  background: var(--grad);
  border-radius: var(--r-md);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 19px; color: #fff;
  box-shadow: var(--shadow-sm);
  letter-spacing: 0;
}
.header-title { font-size: var(--fs-lg); font-weight: 650; letter-spacing: -0.01em; }
.header-sub { font-size: var(--fs-xs); color: var(--text-mute); margin-top: 1px; letter-spacing: 0.02em; }
.header-spacer { flex: 1; }
.btn-icon {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 7px;
  cursor: pointer;
  color: var(--text-dim);
  display: inline-flex; align-items: center; justify-content: center;
  transition: color .15s, border-color .15s, background .15s, box-shadow .15s;
}
.btn-icon:hover { color: var(--text); border-color: var(--accent); background: var(--accent-soft); }
.btn-icon:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--accent-ring); }
.btn-icon svg { width: 18px; height: 18px; display: block; }

/* ── Tabs ───────────────────────────────────────────────────────── */
.tabs {
  display: flex;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 0 var(--sp-5);
  gap: 2px;
  flex-shrink: 0;
}
.tab {
  padding: var(--sp-2) var(--sp-4);
  cursor: pointer;
  font-size: var(--fs-md);
  font-weight: 500;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s, background .15s;
  user-select: none;
  position: relative;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }

/* ── Content ────────────────────────────────────────────────────── */
.content { flex: 1; overflow: hidden; padding: var(--sp-3) var(--sp-5); min-height: 0; }
.tab-content { display: none; height: 100%; flex-direction: column; gap: var(--sp-3); }
.tab-content.active { display: flex; }

/* ── Controls ───────────────────────────────────────────────────── */
.controls {
  display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap;
  flex-shrink: 0;
}
.control-group { display: flex; align-items: center; gap: var(--sp-2); }
.control-group label {
  font-size: var(--fs-xs); color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600;
}
select {
  background: var(--surface2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 6px 28px 6px 10px;
  font-size: var(--fs-md);
  font-family: var(--font-ui);
  cursor: pointer;
  outline: none;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239aa0b0' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat;
  background-position: right 8px center;
  transition: border-color .15s, box-shadow .15s;
}
select:hover { border-color: var(--border-2); }
select:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); }

.btn {
  border: 1px solid transparent;
  border-radius: var(--r-sm);
  padding: 7px 18px;
  font-size: var(--fs-md);
  font-weight: 600;
  font-family: var(--font-ui);
  cursor: pointer;
  transition: background .15s, border-color .15s, color .15s, box-shadow .15s, transform .05s;
}
.btn:active { transform: translateY(1px); }
.btn:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--accent-ring); }
.btn-primary {
  background: var(--accent); color: #fff;
  box-shadow: var(--shadow-xs);
}
.btn-primary:hover { background: var(--accent-hover); box-shadow: var(--shadow-sm); }
.btn-primary:disabled { opacity: 0.45; cursor: not-allowed; box-shadow: none; transform: none; }
.btn-secondary {
  background: var(--surface2); color: var(--text-dim);
  border: 1px solid var(--border);
}
.btn-secondary:hover { color: var(--text); border-color: var(--border-2); background: var(--surface3); }
.btn-small { padding: 5px 11px; font-size: var(--fs-sm); }
.btn-row { display: flex; gap: var(--sp-2); margin-left: auto; }

/* ── Fields ─────────────────────────────────────────────────────── */
.field-label {
  font-size: var(--fs-xs); color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.04em; font-weight: 600;
  margin-bottom: var(--sp-1); display: flex; justify-content: space-between; align-items: baseline;
}
.field-label .count {
  color: var(--text-mute); font-weight: 500; text-transform: none; letter-spacing: 0;
  font-variant-numeric: tabular-nums;
}
textarea {
  background: var(--surface2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  font-size: var(--fs-base);
  font-family: var(--font-ui);
  resize: none;
  outline: none;
  line-height: var(--lh-base);
  transition: border-color .15s, box-shadow .15s, background .15s;
  width: 100%;
}
textarea::placeholder { color: var(--text-mute); }
textarea:hover { border-color: var(--border-2); }
textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); background: var(--surface); }
textarea:disabled { opacity: 0.55; }
.input-area { height: 110px; }
.output-area { height: 110px; }
.rtl { direction: rtl; text-align: right; }

/* ── Provenance ─────────────────────────────────────────────────── */
.prov-section {
  background: var(--surface3);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  margin-bottom: var(--sp-2);
  overflow: hidden;
  box-shadow: var(--shadow-xs);
  transition: border-color .15s, box-shadow .15s;
}
.prov-section:hover { border-color: var(--border-2); }
.prov-header {
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--accent);
  cursor: pointer;
  user-select: none;
  display: flex; align-items: center; gap: var(--sp-2);
  background: var(--surface2);
  border-bottom: 1px solid transparent;
  transition: background .15s, border-color .15s;
}
.prov-header:hover { background: var(--surface3); }
.prov-header .arrow { transition: transform .2s ease; display: inline-flex; }
.prov-header.collapsed { border-bottom-color: transparent; }
.prov-header.collapsed .arrow { transform: rotate(-90deg); }
.prov-body {
  padding: var(--sp-3);
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  white-space: pre-wrap;
  font-family: var(--font-mono);
  color: var(--text);
  border-top: 1px solid var(--border);
  background: var(--surface3);
}
.prov-body.hidden { display: none; }
.prov-empty {
  color: var(--text-mute);
  font-size: var(--fs-sm);
  padding: var(--sp-6);
  text-align: center;
  display: flex; flex-direction: column; align-items: center; gap: var(--sp-2);
}

/* ── Audit trace ────────────────────────────────────────────────── */
.trace-area {
  flex: 1;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  overflow-y: auto;
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  white-space: pre-wrap;
  font-family: var(--font-mono);
  color: var(--text);
}

/* ── History ────────────────────────────────────────────────────── */
.history-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: var(--sp-2); padding-right: var(--sp-1); }
.history-item {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  cursor: pointer;
  transition: border-color .15s, box-shadow .15s, transform .1s;
  box-shadow: var(--shadow-xs);
}
.history-item:hover { border-color: var(--accent); box-shadow: var(--shadow-sm); transform: translateY(-1px); }
.history-input {
  font-size: var(--fs-sm); color: var(--text); margin-bottom: var(--sp-1);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.history-output {
  font-size: var(--fs-sm); color: var(--text-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.history-dir {
  font-size: var(--fs-xs); color: var(--accent); font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: var(--sp-1);
  display: inline-block;
}
.history-empty {
  color: var(--text-mute); font-size: var(--fs-md);
  text-align: center; padding: var(--sp-8);
  display: flex; flex-direction: column; align-items: center; gap: var(--sp-2);
}

/* ── Status bar ─────────────────────────────────────────────────── */
.status-bar {
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: var(--sp-2) var(--sp-5);
  font-size: var(--fs-xs);
  color: var(--text-dim);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.status-indicator { display: flex; align-items: center; gap: var(--sp-2); }
.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--text-mute);
  transition: background .2s;
}
.status-dot.active { background: var(--warn); animation: pulse 1.2s ease-in-out infinite; }
.status-dot.success { background: var(--success); box-shadow: 0 0 0 3px rgba(52,211,153,0.18); }
.status-dot.error { background: var(--error); box-shadow: 0 0 0 3px rgba(248,113,113,0.18); }
@keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.85); } }
.store-badge {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--r-xs);
  padding: 2px var(--sp-2);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}
.store-badge .num { color: var(--accent); font-weight: 600; }

/* ── Spinner ────────────────────────────────────────────────────── */
.spinner {
  display: inline-block;
  width: 16px; height: 16px;
  border: 2px solid var(--border-2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Skeleton shimmer (loading state) ───────────────────────────── */
.skeleton {
  background: linear-gradient(90deg, var(--surface2) 25%, var(--surface3) 37%, var(--surface2) 63%);
  background-size: 400% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: var(--r-sm);
}
@keyframes shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }
.skel-line { height: 10px; margin-bottom: 8px; border-radius: var(--r-xs); }
.skel-line:last-child { margin-bottom: 0; width: 70%; }

/* ── Inline icon helper ─────────────────────────────────────────── */
.icon { width: 16px; height: 16px; display: inline-block; vertical-align: middle; flex-shrink: 0; }
.icon-sm { width: 14px; height: 14px; }
.empty-icon { color: var(--text-mute); opacity: 0.5; margin-bottom: var(--sp-1); }
</style>
</head>
<body>

<div class="header">
  <div class="header-logo">ع</div>
  <div>
    <div class="header-title">Iraqi Legal Translation Agent</div>
    <div class="header-sub">v2.1 · Professional Edition</div>
  </div>
  <div class="header-spacer"></div>
  <button class="btn-icon" onclick="toggleTheme()" title="Toggle theme" aria-label="Toggle theme">
    <svg id="icon-theme" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>
    </svg>
  </button>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab(event,'translate')">Translate</div>
  <div class="tab" onclick="switchTab(event,'trace')">Audit Trace</div>
  <div class="tab" onclick="switchTab(event,'history')">History</div>
</div>

<div class="content">

  <!-- Translate Tab -->
  <div id="tab-translate" class="tab-content active">
    <div class="controls">
      <div class="control-group">
        <label>Direction</label>
        <select id="direction">
          <option value="ar-en">AR &rarr; EN</option>
          <option value="en-ar">EN &rarr; AR</option>
        </select>
      </div>
      <div class="control-group">
        <label>Model</label>
        <select id="model"></select>
      </div>
      <div class="control-group">
        <label>Example</label>
        <select id="example" onchange="loadExample()">
          <option value="">-- Select --</option>
        </select>
      </div>
      <div class="btn-row">
        <button class="btn btn-secondary btn-small" onclick="clearAll()" title="Clear all fields">
          <svg class="icon-sm" style="vertical-align:-2px;margin-right:4px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>Clear
        </button>
        <button class="btn btn-primary" id="btn-translate"
          onclick="doTranslate()" title="Translate (Ctrl+Enter)">
          <svg class="icon-sm" style="vertical-align:-2px;margin-right:4px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>Translate
        </button>
      </div>
    </div>

    <div>
      <div class="field-label">
        <span>Source Text</span>
        <span class="count" id="input-count">0 chars · 0 words</span>
      </div>
      <textarea id="input" class="input-area"
        placeholder="Enter legal text... (Ctrl+Enter to translate)"></textarea>
    </div>

    <div>
      <div class="field-label">
        <span>Translation</span>
        <span class="count" id="output-meta"></span>
      </div>
      <div style="display:flex;gap:6px;align-items:flex-start;">
        <textarea id="output" class="output-area" readonly style="flex:1;"></textarea>
        <button class="btn btn-secondary btn-small" onclick="copyOutput()"
          title="Copy translation" style="margin-top:2px;">
          <svg class="icon-sm" style="vertical-align:-2px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        </button>
      </div>
    </div>

    <div style="flex:1;display:flex;flex-direction:column;min-height:0;">
      <div class="field-label">Provenance</div>
      <div id="provenance" style="flex:1;overflow-y:auto;">
        <div class="prov-empty">
          <svg class="icon empty-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>
          <span>Provenance will appear after translation.</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Audit Trace Tab -->
  <div id="tab-trace" class="tab-content">
    <div class="field-label">Full Revision History</div>
    <div id="trace" class="trace-area" style="display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text-mute);">
      <svg class="icon empty-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13l2 2 4-4"/></svg>
      <span style="margin-top:8px;">Audit trace will appear after translation.</span>
    </div>
  </div>

  <!-- History Tab -->
  <div id="tab-history" class="tab-content">
    <div class="field-label">Recent Translations (last 10)</div>
    <div id="history-list" class="history-list">
      <div class="history-empty">
        <svg class="icon empty-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <span>No translations yet.</span>
      </div>
    </div>
  </div>

</div>

<div class="status-bar">
  <div class="status-indicator">
    <div class="status-dot" id="status-dot"></div>
    <span id="status-text">Ready</span>
    <span id="timer" style="margin-left:8px;color:var(--text-dim);"></span>
  </div>
  <div style="display:flex;gap:6px;">
    <span class="store-badge">Glossary: <span class="num" id="cnt-glossary">--</span></span>
    <span class="store-badge">RAG: <span class="num" id="cnt-chroma">--</span></span>
    <span class="store-badge">TM: <span class="num" id="cnt-tm">--</span></span>
  </div>
</div>

<script>
let pollTimer = null;
let startTime = 0;
let timerInterval = null;

// ── Reusable SVG icons & empty-state markup ───────────────────────
const ICON = {
  doc:  '<svg class="icon empty-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>',
  trace:'<svg class="icon empty-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13l2 2 4-4"/></svg>',
  clock:'<svg class="icon empty-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  alert:'<svg class="icon empty-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
};
const PROV_EMPTY   = '<div class="prov-empty">' + ICON.doc + '<span>Provenance will appear after translation.</span></div>';
const TRACE_EMPTY  = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text-mute);height:100%;">' + ICON.trace + '<span style="margin-top:8px;">Audit trace will appear after translation.</span></div>';
const HISTORY_EMPTY= '<div class="history-empty">' + ICON.clock + '<span>No translations yet.</span></div>';
function skeletonLines(n) {
  let s = '<div class="prov-empty" style="align-items:stretch;text-align:left;width:100%;">';
  for (let i=0;i<n;i++) s += '<div class="skeleton skel-line"></div>';
  s += '</div>';
  return s;
}

async function init() {
  // Models
  const models = await pywebview.api.get_models();
  const defaultModel = await pywebview.api.get_default_model();
  const sel = document.getElementById('model');
  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    sel.appendChild(opt);
  });
  sel.value = defaultModel;

  // Examples
  const examples = await pywebview.api.get_examples();
  const exSel = document.getElementById('example');
  examples.forEach(e => {
    const opt = document.createElement('option');
    opt.value = e.text; opt.textContent = e.label;
    exSel.appendChild(opt);
  });

  // Store counts
  const counts = await pywebview.api.get_store_counts();
  document.getElementById('cnt-glossary').textContent = counts.glossary;
  document.getElementById('cnt-chroma').textContent = counts.chroma;
  document.getElementById('cnt-tm').textContent = counts.tm;

  // Event listeners
  document.getElementById('direction').addEventListener('change', toggleRtl);
  document.getElementById('input').addEventListener('input', updateCount);
  document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault(); doTranslate();
    }
  });
  toggleRtl();
  updateCount();
}

function toggleRtl() {
  const dir = document.getElementById('direction').value;
  const input = document.getElementById('input');
  if (dir === 'ar-en') {
    input.classList.add('rtl'); input.setAttribute('dir', 'rtl');
  } else {
    input.classList.remove('rtl'); input.setAttribute('dir', 'ltr');
  }
}

function updateCount() {
  const text = document.getElementById('input').value;
  const chars = text.length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  document.getElementById('input-count').textContent =
    chars + ' chars \u00b7 ' + words + ' words';
}

function loadExample() {
  const sel = document.getElementById('example');
  if (sel.value) {
    document.getElementById('input').value = sel.value;
    updateCount();
    // Auto-set direction based on content
    const dir = document.getElementById('direction');
    if (/[\u0600-\u06FF]/.test(sel.value)) dir.value = 'ar-en';
    else dir.value = 'en-ar';
    toggleRtl();
  }
}

function switchTab(ev, name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content')
    .forEach(c => c.classList.remove('active'));
  ev.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'history') loadHistory();
}

function clearAll() {
  document.getElementById('input').value = '';
  document.getElementById('output').value = '';
  document.getElementById('provenance').innerHTML = PROV_EMPTY;
  document.getElementById('trace').innerHTML = TRACE_EMPTY;
  document.getElementById('output-meta').textContent = '';
  document.getElementById('example').value = '';
  updateCount();
  setStatus('', 'Ready');
}

async function copyOutput() {
  const text = document.getElementById('output').value;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch(e) {
    document.getElementById('output').select();
    document.execCommand('copy');
  }
}

async function doTranslate() {
  const input = document.getElementById('input').value;
  const direction = document.getElementById('direction').value;
  const model = document.getElementById('model').value;

  if (!input.trim()) {
    setStatus('error', 'Input is empty');
    return;
  }

  document.getElementById('btn-translate').disabled = true;
  document.getElementById('output').value = '';
  document.getElementById('provenance').innerHTML = skeletonLines(4);
  document.getElementById('trace').textContent = '';
  document.getElementById('output-meta').textContent = '';
  setStatus('active', 'Translating\u2026');

  startTime = Date.now();
  timerInterval = setInterval(function() {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    document.getElementById('timer').textContent = elapsed + 's';
  }, 100);

  const result = await pywebview.api.translate(input, direction, model);
  if (result === 'empty') {
    setStatus('error', 'Input is empty');
    document.getElementById('btn-translate').disabled = false;
    clearInterval(timerInterval);
    return;
  }
  pollTimer = setInterval(pollResult, 300);
}

async function pollResult() {
  const r = await pywebview.api.get_result();
  if (r.status === 'translating') return;

  clearInterval(pollTimer); pollTimer = null;
  clearInterval(timerInterval); timerInterval = null;
  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  document.getElementById('btn-translate').disabled = false;

  if (r.status === 'ok') {
    document.getElementById('output').value = r.translation;
    renderProvenance(r.provenance);
    document.getElementById('trace').textContent = r.audit_trace;
    const dir = document.getElementById('direction').value;
    const out = document.getElementById('output');
    if (dir === 'en-ar') {
      out.classList.add('rtl'); out.setAttribute('dir', 'rtl');
    } else {
      out.classList.remove('rtl'); out.setAttribute('dir', 'ltr');
    }
    const words = r.translation.trim().split(/\s+/).length;
    document.getElementById('output-meta').textContent =
      words + ' words \u00b7 ' + elapsed + 's';
    setStatus('success', 'Complete (' + elapsed + 's)');
  } else if (r.status === 'error') {
    document.getElementById('output').value = 'Error: ' + r.error;
    document.getElementById('trace').innerHTML =
      '<div class="prov-empty" style="color:var(--error);">' + ICON.alert +
      '<span>Translation failed. See output for details.</span></div>';
    document.getElementById('output-meta').textContent = '';
    setStatus('error', 'Failed');
  }
  document.getElementById('timer').textContent = '';
}

function renderProvenance(md) {
  const container = document.getElementById('provenance');
  if (!md || !md.trim()) {
    container.innerHTML = '<div class="prov-empty">' + ICON.doc + '<span>No provenance data.</span></div>';
    return;
  }
  // Parse markdown-like sections (## headers).
  const sections = md.split(/^## /m).filter(s => s.trim());
  if (sections.length <= 1) {
    container.innerHTML =
      '<div class="prov-body">' + escHtml(md) + '</div>';
    return;
  }
  container.innerHTML = '';
  sections.forEach(function(s) {
    const lines = s.split('\n');
    const title = lines[0].trim();
    const body = lines.slice(1).join('\n').trim();
    const sec = document.createElement('div');
    sec.className = 'prov-section';
    const hdr = document.createElement('div');
    hdr.className = 'prov-header';
    hdr.innerHTML = '<span class="arrow"><svg class="icon-sm" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></span> ' + escHtml(title);
    const bdy = document.createElement('div');
    bdy.className = 'prov-body';
    bdy.textContent = body;
    hdr.onclick = function() {
      hdr.classList.toggle('collapsed');
      bdy.classList.toggle('hidden');
    };
    sec.appendChild(hdr);
    sec.appendChild(bdy);
    container.appendChild(sec);
  });
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function loadHistory() {
  const items = await pywebview.api.get_history();
  const list = document.getElementById('history-list');
  if (!items.length) {
    list.innerHTML = HISTORY_EMPTY;
    return;
  }
  list.innerHTML = '';
  items.reverse().forEach(function(item) {
    const div = document.createElement('div');
    div.className = 'history-item';
    div.innerHTML =
      '<div class="history-dir">' + escHtml(item.direction) + '</div>' +
      '<div class="history-input">' + escHtml(item.input) + '</div>' +
      '<div class="history-output">' + escHtml(item.translation) + '</div>';
    div.onclick = function() {
      document.getElementById('input').value = item.input;
      document.getElementById('direction').value = item.direction;
      document.getElementById('output').value = item.translation;
      renderProvenance(item.provenance);
      document.getElementById('trace').textContent = item.audit_trace;
      toggleRtl(); updateCount();
      switchTab({target: document.querySelector('.tab')}, 'translate');
      document.querySelector('.tab').classList.add('active');
    };
    list.appendChild(div);
  });
}

function setStatus(state, text) {
  const dot = document.getElementById('status-dot');
  const cls = state === 'active' ? 'active'
    : state === 'success' ? 'success'
    : state === 'error' ? 'error' : '';
  dot.className = 'status-dot ' + cls;
  document.getElementById('status-text').textContent = text;
}

function toggleTheme() {
  const html = document.documentElement;
  const cur = html.getAttribute('data-theme');
  const next = cur === 'light' ? '' : 'light';
  html.setAttribute('data-theme', next);
  // Swap the icon: sun (in dark mode, click to go light) / moon (in light mode).
  const sun  = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';
  const moon = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
  document.getElementById('icon-theme').innerHTML = next === 'light' ? moon : sun;
}

window.addEventListener('pywebviewready', init);
</script>

</body>
</html>"""


def launch_ui(cfg: AppConfig, adapters: Adapters) -> None:
    """Build and run the pywebview desktop UI.

    Called by the CLI ``ui`` command. ``cfg`` and ``adapters`` are
    constructed by the CLI (the only place concrete adapters are built,
    engineering-principles §3.6) and injected here.
    """
    api: Api = Api(cfg, adapters)
    webview.create_window(
        title="Iraqi Legal Translation Agent",
        html=_HTML,
        js_api=api,
        width=960,
        height=800,
        min_size=(750, 600),
        text_select=True,
    )
    webview.start()
