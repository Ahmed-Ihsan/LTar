"""Web frontend HTML template (extracted from web_ui.py — SRP).

Single embedded HTML document with no external assets. Kept as a raw string
constant so the webview window loads instantly without file I/O.
"""
from __future__ import annotations

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

/* ── Excel tab ──────────────────────────────────────────────────── */
.excel-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-5);
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-4);
  flex-shrink: 0;
}
.excel-col { display: flex; flex-direction: column; gap: var(--sp-1); }
.picker-row { display: flex; align-items: center; gap: var(--sp-2); }
.picker-path {
  font-size: var(--fs-sm); color: var(--text-dim);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; font-family: var(--font-mono);
}
.xl-opt {
  display: flex; align-items: center; gap: var(--sp-2);
  font-size: var(--fs-md); color: var(--text); cursor: pointer;
  padding: var(--sp-1) 0;
}
.xl-opt input { width: 16px; height: 16px; cursor: pointer; accent-color: var(--accent); }
.xl-num {
  background: var(--surface2); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--r-sm);
  padding: 6px 10px; font-size: var(--fs-md); font-family: var(--font-ui);
  width: 120px; outline: none;
}
.xl-num:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); }
.xl-error {
  background: rgba(248,113,113,0.10); border: 1px solid var(--error);
  border-radius: var(--r-md); padding: var(--sp-3); color: var(--error);
  font-size: var(--fs-sm); flex-shrink: 0;
}
.xl-progress { display: flex; flex-direction: column; gap: var(--sp-2); flex-shrink: 0; }
.xl-bar-track {
  height: 8px; background: var(--surface3); border-radius: var(--r-xs);
  overflow: hidden; border: 1px solid var(--border);
}
.xl-bar-fill {
  height: 100%; width: 0%; background: var(--grad);
  transition: width .2s ease;
}
.xl-current {
  font-size: var(--fs-xs); color: var(--text-mute);
  font-family: var(--font-mono); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.xl-report { display: flex; flex-direction: column; gap: var(--sp-2); flex: 1; min-height: 0; }
.xl-report-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-2); flex-shrink: 0;
}
.xl-stat {
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--r-sm); padding: var(--sp-2) var(--sp-3);
  display: flex; flex-direction: column; gap: 2px;
}
.xl-stat .label {
  font-size: var(--fs-xs); color: var(--text-mute);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.xl-stat .value {
  font-size: var(--fs-lg); font-weight: 600; color: var(--accent);
  font-variant-numeric: tabular-nums;
}
.xl-warnings {
  flex: 1; overflow-y: auto; background: var(--surface2);
  border: 1px solid var(--border); border-radius: var(--r-md);
  padding: var(--sp-3); font-size: var(--fs-sm); font-family: var(--font-mono);
  color: var(--text-dim); white-space: pre-wrap; min-height: 60px;
}

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
  <div class="tab" onclick="switchTab(event,'excel')">Excel</div>
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

  <!-- Excel Tab -->
  <div id="tab-excel" class="tab-content">
    <div class="excel-form">
      <div class="excel-col">
        <div class="field-label">Input Workbook (.xlsx)</div>
        <div class="picker-row">
          <button class="btn btn-secondary btn-small" onclick="pickExcelInput()">Browse…</button>
          <span id="xl-input-path" class="picker-path">No file selected</span>
        </div>
        <div class="field-label" style="margin-top:var(--sp-4);">Output Workbook (.xlsx)</div>
        <div class="picker-row">
          <button class="btn btn-secondary btn-small" onclick="pickExcelOutput()">Save As…</button>
          <span id="xl-output-path" class="picker-path">No file selected</span>
        </div>
        <div class="control-group" style="margin-top:var(--sp-4);">
          <label>Direction</label>
          <select id="xl-direction">
            <option value="ar-en">AR &rarr; EN</option>
            <option value="en-ar">EN &rarr; AR</option>
          </select>
        </div>
      </div>
      <div class="excel-col">
        <div class="field-label">Excel Options</div>
        <label class="xl-opt"><input type="checkbox" id="xl-opt-comments" checked> Translate comments</label>
        <label class="xl-opt"><input type="checkbox" id="xl-opt-headers" checked> Translate headers &amp; footers</label>
        <label class="xl-opt"><input type="checkbox" id="xl-opt-charts" checked> Translate chart titles</label>
        <div class="field-label" style="margin-top:var(--sp-3);">Max segment chars</div>
        <input type="number" id="xl-opt-maxchars" min="16" value="4096" class="xl-num">
      </div>
    </div>

    <div class="controls">
      <button class="btn btn-primary" id="btn-xl-translate" onclick="doTranslateExcel()" disabled>Translate Excel</button>
      <button class="btn btn-secondary" id="btn-xl-cancel" onclick="cancelExcel()" style="display:none;">Cancel</button>
      <button class="btn btn-secondary btn-small" id="btn-xl-open" onclick="openExcelOutput()" style="display:none;margin-left:auto;">Open output</button>
    </div>

    <div id="xl-error" class="xl-error" style="display:none;"></div>

    <div id="xl-progress" class="xl-progress" style="display:none;">
      <div class="field-label">
        <span>Progress</span>
        <span class="count" id="xl-counter">0 / 0</span>
      </div>
      <div class="xl-bar-track"><div id="xl-bar-fill" class="xl-bar-fill"></div></div>
      <div id="xl-current" class="xl-current"></div>
    </div>

    <div id="xl-report" class="xl-report" style="display:none;">
      <div class="field-label">Report</div>
      <div class="xl-report-grid" id="xl-report-grid"></div>
      <div class="field-label" style="margin-top:var(--sp-3);">Warnings</div>
      <div id="xl-warnings" class="xl-warnings"></div>
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
  initExcel();
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
  if (name === 'translate') refreshTranslateButtonBusy();
}

// ── Excel tab ─────────────────────────────────────────────────────
let xlState = {
  inputPath: null, outputPath: null, jobId: null,
  pollTimer: null, running: false,
};

async function initExcel() {
  const opts = await pywebview.api.get_excel_options();
  document.getElementById('xl-opt-comments').checked = opts.translate_comments;
  document.getElementById('xl-opt-headers').checked = opts.translate_headers_footers;
  document.getElementById('xl-opt-charts').checked = opts.translate_chart_titles;
  document.getElementById('xl-opt-maxchars').value = opts.max_segment_chars;
  ['xl-input-path','xl-output-path','xl-direction','xl-opt-comments','xl-opt-headers','xl-opt-charts','xl-opt-maxchars']
    .forEach(id => document.getElementById(id).addEventListener('change', updateExcelButtonState));
  updateExcelButtonState();
}

async function pickExcelInput() {
  const path = await pywebview.api.pick_excel_input(window.__SESSION_TOKEN);
  if (path) {
    xlState.inputPath = path;
    document.getElementById('xl-input-path').textContent = path;
    // Auto-suggest output: <stem>_translated.xlsx in the same directory.
    if (!xlState.outputPath) {
      const stem = path.replace(/\.xlsx$/i, '');
      document.getElementById('xl-output-path').textContent = stem + '_translated.xlsx (suggested)';
      xlState.outputPath = stem + '_translated.xlsx';
    }
    updateExcelButtonState();
  }
}

async function pickExcelOutput() {
  const defaultName = xlState.inputPath
    ? xlState.inputPath.replace(/\.xlsx$/i, '') + '_translated.xlsx'
    : 'workbook_translated.xlsx';
  const path = await pywebview.api.pick_excel_output(window.__SESSION_TOKEN, defaultName);
  if (path) {
    xlState.outputPath = path;
    document.getElementById('xl-output-path').textContent = path;
    updateExcelButtonState();
  }
}

function updateExcelButtonState() {
  const ready = xlState.inputPath && xlState.outputPath && !xlState.running;
  document.getElementById('btn-xl-translate').disabled = !ready;
}

async function refreshTranslateButtonBusy() {
  // Cross-tab disablement: disable the single-sentence Translate button
  // while an Excel run is in progress (concurrency = 1).
  const busy = await pywebview.api.is_busy();
  document.getElementById('btn-translate').disabled = busy;
}

function xlOptions() {
  return {
    translate_comments: document.getElementById('xl-opt-comments').checked,
    translate_headers_footers: document.getElementById('xl-opt-headers').checked,
    translate_chart_titles: document.getElementById('xl-opt-charts').checked,
    max_segment_chars: parseInt(document.getElementById('xl-opt-maxchars').value, 10) || 4096,
  };
}

async function doTranslateExcel() {
  if (!xlState.inputPath || !xlState.outputPath) return;
  // Overwrite confirmation.
  const exists = await pywebview.api.path_exists(xlState.outputPath);
  if (exists && !confirm('Output file already exists. Overwrite?')) return;
  document.getElementById('xl-error').style.display = 'none';
  document.getElementById('xl-report').style.display = 'none';
  document.getElementById('xl-progress').style.display = 'flex';
  document.getElementById('xl-bar-fill').style.width = '0%';
  document.getElementById('xl-counter').textContent = '0 / 0';
  document.getElementById('xl-current').textContent = '';
  document.getElementById('btn-xl-translate').disabled = true;
  document.getElementById('btn-xl-cancel').style.display = 'inline-block';
  document.getElementById('btn-xl-open').style.display = 'none';
  xlState.running = true;
  setStatus('active', 'Translating Excel\u2026');
  refreshTranslateButtonBusy();

  const direction = document.getElementById('xl-direction').value;
  const res = await pywebview.api.translate_excel(
    window.__SESSION_TOKEN, xlState.inputPath, xlState.outputPath, direction, xlOptions()
  );
  if (res.state === 'error') {
    xlRunEnded();
    showExcelError(res.error);
    return;
  }
  xlState.jobId = res.job_id;
  xlState.pollTimer = setInterval(pollExcelStatus, 300);
}

async function pollExcelStatus() {
  const s = await pywebview.api.get_excel_status(xlState.jobId);
  if (s.state === 'running') {
    const pct = s.total > 0 ? Math.round((s.completed / s.total) * 100) : 0;
    document.getElementById('xl-bar-fill').style.width = pct + '%';
    document.getElementById('xl-counter').textContent = s.completed + ' / ' + s.total;
    document.getElementById('xl-current').textContent = s.current ? truncate(s.current, 80) : '';
    return;
  }
  clearInterval(xlState.pollTimer); xlState.pollTimer = null;
  document.getElementById('xl-bar-fill').style.width = '100%';
  document.getElementById('xl-progress').style.display = 'none';
  document.getElementById('btn-xl-cancel').style.display = 'none';
  if (s.state === 'done' || s.state === 'cancelled') {
    renderExcelReport(s.report, s.state === 'cancelled');
    document.getElementById('btn-xl-open').style.display = 'inline-block';
    setStatus(s.state === 'cancelled' ? 'success' : 'success',
      s.state === 'cancelled' ? 'Cancelled (partial output written)' : 'Excel complete');
  } else if (s.state === 'error') {
    showExcelError(s.error);
    setStatus('error', 'Excel run failed');
  }
  xlRunEnded();
}

function xlRunEnded() {
  xlState.running = false;
  updateExcelButtonState();
  refreshTranslateButtonBusy();
}

function showExcelError(msg) {
  const el = document.getElementById('xl-error');
  el.textContent = msg || 'Unknown error';
  el.style.display = 'block';
  document.getElementById('xl-progress').style.display = 'none';
  setStatus('error', 'Excel run failed');
}

function renderExcelReport(r, cancelled) {
  const grid = document.getElementById('xl-report-grid');
  const stats = [
    ['Total', r.total_segments], ['Translated', r.translated],
    ['Skipped', r.skipped], ['Failed', r.failed],
    ['Cancelled', r.cancelled ? 'Yes' : 'No'],
  ];
  grid.innerHTML = stats.map(function(s) {
    return '<div class="xl-stat"><span class="label">' + s[0] + '</span>' +
      '<span class="value">' + s[1] + '</span></div>';
  }).join('');
  const w = document.getElementById('xl-warnings');
  w.textContent = r.warnings && r.warnings.length
    ? r.warnings.join('\n')
    : (cancelled ? 'Run cancelled; remaining segments kept their original text.'
       : 'No warnings.');
  document.getElementById('xl-report').style.display = 'flex';
}

async function cancelExcel() {
  if (xlState.jobId) await pywebview.api.cancel_excel(xlState.jobId);
}

async function openExcelOutput() {
  if (xlState.outputPath) await pywebview.api.open_in_explorer(window.__SESSION_TOKEN, xlState.outputPath);
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + '\u2026' : s;
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

  const result = await pywebview.api.translate(window.__SESSION_TOKEN, input, direction, model);
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

  if (r.status === 'review_pending') {
    // HITL: show the draft in an editable area for human review.
    // Don't stop polling — the worker thread is blocked waiting for
    // submit_review/approve_review. After the human acts, the worker
    // will re-audit and set status to "ok".
    clearInterval(timerInterval); timerInterval = null;
    document.getElementById('btn-translate').disabled = false;
    showReviewPanel(r.translation, r.provenance, r.audit_trace);
    setStatus('active', 'Awaiting human review\u2026');
    return;
  }

  // Hide the review panel if it was shown.
  hideReviewPanel();

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

function showReviewPanel(draft, provenance, auditTrace) {
  // Create or show the HITL review overlay.
  let panel = document.getElementById('review-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'review-panel';
    panel.style.cssText =
      'position:fixed;top:0;left:0;right:0;bottom:0;' +
      'background:var(--bg);z-index:1000;padding:24px;' +
      'display:flex;flex-direction:column;gap:12px;';
    document.body.appendChild(panel);
  }
  const dir = document.getElementById('direction').value;
  const rtlClass = dir === 'en-ar' ? ' dir="rtl" style="direction:rtl"' : '';
  panel.innerHTML =
    '<h2 style="margin:0;color:var(--accent);">Human Review (HITL)</h2>' +
    '<p style="margin:0;color:var(--text-mute);">' +
    'Review the AI draft below. Edit the text and click Submit, or click ' +
    'Approve to accept it as-is. Your edits will be saved to teach the model.' +
    '</p>' +
    '<textarea id="review-edit" style="flex:1;min-height:200px;' +
    'font-size:15px;padding:12px;border:1px solid var(--border);' +
    'border-radius:var(--r-md);background:var(--surface);color:var(--text);' +
    'resize:vertical;"' + rtlClass + '>' + escHtml(draft) + '</textarea>' +
    '<div style="display:flex;gap:12px;justify-content:flex-end;">' +
    '<button id="btn-approve" onclick="approveDraft()" style="padding:10px 24px;' +
    'border:1px solid var(--border);border-radius:var(--r-md);' +
    'background:var(--surface);color:var(--text);cursor:pointer;">Approve</button>' +
    '<button id="btn-submit-edit" onclick="submitEdit()" style="padding:10px 24px;' +
    'border:none;border-radius:var(--r-md);background:var(--accent);' +
    'color:#fff;cursor:pointer;font-weight:600;">Submit Edit</button>' +
    '</div>';
  panel.style.display = 'flex';
  // Show provenance + audit trace in the background panels.
  renderProvenance(provenance);
  document.getElementById('trace').textContent = auditTrace;
}

function hideReviewPanel() {
  const panel = document.getElementById('review-panel');
  if (panel) panel.style.display = 'none';
}

async function approveDraft() {
  await pywebview.api.approve_review(window.__SESSION_TOKEN);
  setStatus('active', 'Finalizing\u2026');
  startTime = Date.now();
  timerInterval = setInterval(function() {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    document.getElementById('timer').textContent = elapsed + 's';
  }, 100);
  pollTimer = setInterval(pollResult, 300);
}

async function submitEdit() {
  const edited = document.getElementById('review-edit').value;
  await pywebview.api.submit_review(window.__SESSION_TOKEN, edited);
  setStatus('active', 'Re-auditing edit\u2026');
  startTime = Date.now();
  timerInterval = setInterval(function() {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    document.getElementById('timer').textContent = elapsed + 's';
  }, 100);
  pollTimer = setInterval(pollResult, 300);
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
