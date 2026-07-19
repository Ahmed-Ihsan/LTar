"""Environment diagnostics for the ``doctor`` command (task 1.3.3).

Extracted from ``cli.py`` (engineering-principles §1.1 single-responsibility).
Each check is a small, single-purpose function returning a
:class:`~src.components.interfaces.models.CheckResult`; the ``doctor``
command coordinates them and renders a green-check / red-failure summary.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import ollama
import typer

from src.components.infrastructure.memory import MemoryInfo, read_memory_info
from src.components.interfaces.models import CheckResult
from src.config import AppConfig

# RAM budget per README.md §3 (GB). Sum = 8.0 GB, the hard ceiling.
_RAM_BUDGET_OS_GB: float = 1.8
_RAM_BUDGET_LLM_GB: float = 3.0
_RAM_BUDGET_EMBED_GB: float = 0.3
_RAM_BUDGET_CHROMA_GB: float = 0.5
_RAM_BUDGET_PYTHON_GB: float = 0.4
_RAM_BUDGET_TOTAL_GB: float = (
    _RAM_BUDGET_OS_GB
    + _RAM_BUDGET_LLM_GB
    + _RAM_BUDGET_EMBED_GB
    + _RAM_BUDGET_CHROMA_GB
    + _RAM_BUDGET_PYTHON_GB
)  # 6.0 GB of fixed components; 2.0 GB reserved as ingestion headroom


def _resolve_path(cfg: AppConfig, rel: str) -> Path:
    """Resolve a config-relative path against the project root.

    Thin delegate to :func:`src.components.interfaces.cli._resolve_path` to
    avoid duplicating the project-root logic (DRY). Imported lazily to break
    the circular dependency between this module and ``cli``.
    """
    from src.components.interfaces.cli import _resolve_path as _cli_resolve_path

    return _cli_resolve_path(cfg, rel)


def _check_ollama_reachable(client: ollama.Client) -> CheckResult:
    """Verify the Ollama daemon is reachable and responding."""
    try:
        client.list()
    except (ConnectionError, OSError) as e:
        return CheckResult(
            "Ollama daemon reachable",
            ok=False,
            detail=f"cannot connect to Ollama: {e}",
        )
    return CheckResult(
        "Ollama daemon reachable",
        ok=True,
        detail="connected, /api/tags responded",
    )


def _canonical_model_name(name: str | None) -> str:
    """Normalize an Ollama model name to its canonical tagged form.

    Ollama defaults an omitted tag to ``:latest`` (e.g. ``nomic-embed-text``
    is the same model as ``nomic-embed-text:latest``). This lets a config
    value without a tag match the tagged form reported by ``ollama list``.
    """
    if name is None:
        return ""
    if ":" in name:
        return name
    return f"{name}:latest"


def _list_ollama_models(host: str) -> list[str]:
    """Return the names of models installed on the Ollama instance at ``host``.

    Returns an empty list if the daemon is unreachable (the UI falls back to
    the config default in that case). Used by the Tkinter UI to populate the
    model dropdown.
    """
    try:
        response = ollama.Client(host=host).list()
    except (ConnectionError, OSError):
        return []
    return [m.model for m in response.models if m.model]


def _check_models_present(client: ollama.Client, cfg: AppConfig) -> CheckResult:
    """Verify both the LLM and embedding models are present locally."""
    try:
        response = client.list()
    except (ConnectionError, OSError) as e:
        return CheckResult(
            "Required models present",
            ok=False,
            detail=f"could not list models: {e}",
        )
    installed: set[str] = {
        _canonical_model_name(m.model) for m in response.models
    }
    required: list[str] = [cfg.llm_model, cfg.embed_model]
    missing: list[str] = [
        name for name in required
        if _canonical_model_name(name) not in installed
    ]
    if missing:
        return CheckResult(
            "Required models present",
            ok=False,
            detail=f"missing: {', '.join(missing)} (run `ollama pull <name>`)",
        )
    return CheckResult(
        "Required models present",
        ok=True,
        detail=f"{cfg.llm_model} + {cfg.embed_model} both installed",
    )


def _check_chroma_dir(cfg: AppConfig) -> CheckResult:
    """Verify the ChromaDB persistent directory exists."""
    chroma_path: Path = _resolve_path(cfg, cfg.paths.chroma_dir)
    if chroma_path.is_dir():
        return CheckResult(
            "ChromaDB directory exists",
            ok=True,
            detail=str(chroma_path),
        )
    return CheckResult(
        "ChromaDB directory exists",
        ok=False,
        detail=f"not found: {chroma_path} (run `python -m src.ingestion --rebuild`)",
    )


def _check_glossary_db(cfg: AppConfig) -> CheckResult:
    """Verify the glossary SQLite DB exists and is non-empty."""
    db_path: Path = _resolve_path(cfg, cfg.paths.glossary_db)
    if not db_path.is_file():
        return CheckResult(
            "Glossary SQLite populated",
            ok=False,
            detail=f"not found: {db_path} (run `python -m src.ingestion --rebuild`)",
        )
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cursor: sqlite3.Cursor = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            table_count: int = int(cursor.fetchone()[0])
    except sqlite3.DatabaseError as e:
        return CheckResult(
            "Glossary SQLite populated",
            ok=False,
            detail=f"cannot read {db_path}: {e}",
        )
    if table_count == 0:
        return CheckResult(
            "Glossary SQLite populated",
            ok=False,
            detail=f"{db_path} exists but contains no tables (ingestion not run)",
        )
    return CheckResult(
        "Glossary SQLite populated",
        ok=True,
        detail=f"{db_path} ({table_count} table{'s' if table_count != 1 else ''})",
    )


def _detect_offload_mode(client: ollama.Client) -> str:
    """Detect GPU-vs-CPU offload of the loaded LLM from ``ollama ps``.

    Returns one of: ``"100% GPU"``, ``"CPU-only"``, ``"partial GPU"``,
    or ``"not loaded"`` (no model currently resident).
    """
    try:
        proc = client.ps()
    except (ConnectionError, OSError):
        return "not loaded"
    if not proc.models:
        return "not loaded"
    loaded = next(
        (m for m in proc.models if m.size and m.size > 0),
        None,
    )
    if loaded is None:
        return "not loaded"
    size: int = int(loaded.size) if loaded.size is not None else 0
    vram: int = int(loaded.size_vram or 0)
    if size == 0:
        return "not loaded"
    ratio: float = vram / size
    if ratio >= 0.999:
        return "100% GPU"
    if ratio <= 0.001:
        return "CPU-only"
    return f"partial GPU ({ratio * 100:.0f}% in VRAM)"


def _check_ram_headroom(client: ollama.Client, cfg: AppConfig) -> CheckResult:
    """Estimate RAM headroom against the 8 GB budget (README.md §3).

    Reports total system RAM, the fixed-component budget, the effective
    headroom, and the LLM offload mode. On a CPU-only target the 7B q5
    model exceeds the 3.0 GB LLM budget line item, so a warning is raised
    (see docs/verification_log.md §1.2.3 caveat).
    """
    mem: MemoryInfo | None = read_memory_info()
    if mem is None:
        return CheckResult(
            "RAM headroom estimate",
            ok=False,
            detail="cannot read system memory on this platform",
        )
    total_gb: float = mem.total_bytes / (1024 ** 3)
    offload: str = _detect_offload_mode(client)

    # Effective system-RAM cost of the LLM depends on offload mode.
    if offload == "100% GPU":
        llm_system_cost_gb: float = 0.9  # runner overhead only; weights in VRAM
    elif offload == "not loaded":
        llm_system_cost_gb = _RAM_BUDGET_LLM_GB  # assume budgeted worst case
    else:
        llm_system_cost_gb = 5.4  # CPU-only / partial: full weights in system RAM

    fixed_cost_gb: float = (
        _RAM_BUDGET_OS_GB + llm_system_cost_gb + _RAM_BUDGET_EMBED_GB
        + _RAM_BUDGET_CHROMA_GB + _RAM_BUDGET_PYTHON_GB
    )
    headroom_gb: float = total_gb - fixed_cost_gb

    detail: str = (
        f"total {total_gb:.1f} GB; fixed budget {fixed_cost_gb:.1f} GB "
        f"(LLM {llm_system_cost_gb:.1f} GB, offload: {offload}); "
        f"headroom ~{headroom_gb:.1f} GB"
    )
    # Hard ceiling is 8 GB. CPU-only offload blows the LLM budget -> warn.
    is_ok: bool = total_gb >= 8.0 and not (
        offload in ("CPU-only",) and headroom_gb < 1.0
    )
    if total_gb < 8.0:
        detail += " [BELOW 8 GB hard ceiling]"
    elif offload == "CPU-only" and headroom_gb < 1.0:
        detail += " [CPU-only: 7B q5 exceeds 3.0 GB LLM budget]"
    return CheckResult("RAM headroom estimate", ok=is_ok, detail=detail)


def _render_result(result: CheckResult) -> None:
    """Render a single check result with a green check or red failure."""
    mark: str = "[OK]  " if result.ok else "[FAIL]"
    color: str = typer.colors.GREEN if result.ok else typer.colors.RED
    typer.secho(f"  {mark} {result.name}: {result.detail}", fg=color)


# ---------------------------------------------------------------------------
# Gemini backend checks (add-gemini-api-backend) — cloud-backend path.
# These run INSTEAD of the Ollama reachability / local-model-presence /
# LLM-RAM-budget checks when `cfg.llm_backend == "gemini"`. ChromaDB /
# glossary / TM checks remain backend-independent and always run.
# ---------------------------------------------------------------------------


def _check_gemini_api_key(cfg: AppConfig) -> CheckResult:
    """Verify the Gemini API key is present (loaded from the env var).

    ``cfg.gemini_api_key`` is populated by ``load_config`` from the
    ``GEMINI_API_KEY`` environment variable. A missing key here means the
    env var was unset/empty at config-load time — ``load_config`` already
    rejects this when ``llm_backend == "gemini"``, so this check is a
    defensive backstop for the case where the env var was unset *after*
    config load (e.g. a long-lived process whose environment changed).
    """
    key: str | None = getattr(cfg, "gemini_api_key", None)
    if key:
        return CheckResult(
            "Gemini API key present",
            ok=True,
            detail="GEMINI_API_KEY is set (value masked for security)",
        )
    return CheckResult(
        "Gemini API key present",
        ok=False,
        detail="GEMINI_API_KEY environment variable is not set",
    )


def _check_gemini_reachable(cfg: AppConfig) -> CheckResult:
    """Verify the Gemini API is reachable and the key is valid.

    Constructs a :class:`GeminiEngineAdapter` and issues a minimal
    ``client.models.list()`` ping. The adapter maps any SDK failure to a
    domain exception (``GeminiAuthError`` / ``LLMConnectionError`` /
    ``LLMRuntimeError``); we surface a short, key-free message in the
    :class:`CheckResult`. The adapter is closed in a ``finally`` so the
    check never leaks a client even on failure.
    """
    from src.components.infrastructure.gemini import GeminiEngineAdapter

    key: str | None = getattr(cfg, "gemini_api_key", None)
    if not key:
        return CheckResult(
            "Gemini API reachable",
            ok=False,
            detail="skipped: GEMINI_API_KEY is not set",
        )
    adapter: GeminiEngineAdapter | None = None
    try:
        try:
            adapter = GeminiEngineAdapter(
                model=cfg.gemini_model,
                embed_model=cfg.gemini_embed_model,
                api_key=key,
                timeout=min(cfg.gemini_timeout, 30.0),
                rpm=cfg.gemini_rpm,
            )
        except Exception as e:  # noqa: BLE001 -- SDK missing / construct failure
            return CheckResult(
                "Gemini API reachable",
                ok=False,
                detail=f"cannot construct Gemini client: {e}",
            )
        # Minimal ping: list available models via the adapter's already-
        # constructed ``google.genai.Client`` (avoids a second Client with a
        # second HTTP pool just for the ping). The adapter maps any SDK
        # failure to a domain exception via ``_translate_gemini_error``.
        client: Any = adapter._client  # noqa: SLF001
        try:
            list_resp: Any = client.models.list()
        except Exception as err:  # noqa: BLE001 -- classify via domain mapper
            from src.components.infrastructure.gemini import _translate_gemini_error
            mapped: Exception = _translate_gemini_error(
                err, model=cfg.gemini_model, kind="llm"
            )
            return CheckResult(
                "Gemini API reachable",
                ok=False,
                detail=f"Gemini API ping failed: {mapped}",
            )
        # Count models defensively (response shape varies across SDK versions).
        count: int = _count_gemini_models(list_resp)
        return CheckResult(
            "Gemini API reachable",
            ok=True,
            detail=f"connected; {count} model(s) visible to this key",
        )
    finally:
        if adapter is not None:
            adapter.close()


def _count_gemini_models(list_resp: Any) -> int:
    """Best-effort count of models in a ``client.models.list()`` response.

    The ``google-genai`` SDK returns an iterable of model objects; the exact
    attribute name has varied across versions (``models``, ``_models``,
    or the response itself is iterable). We inspect defensively so SDK
    drift does not crash the doctor command.
    """
    # Case 1: response is directly iterable.
    try:
        return sum(1 for _ in list_resp)
    except TypeError:
        pass
    # Case 2: response has a `.models` list attribute.
    models: Any = getattr(list_resp, "models", None)
    if models is not None:
        try:
            return len(models)
        except TypeError:
            try:
                return sum(1 for _ in models)
            except TypeError:
                return 0
    return 0


def _check_ram_headroom_gemini(cfg: AppConfig) -> CheckResult:
    """General RAM-headroom check for the Gemini path (LLM-RAM budget skipped).

    Cloud inference does not consume local RAM for model weights (design
    D8), so the LLM-RAM-budget line item from :func:`_check_ram_headroom`
    is irrelevant. ChromaDB, the embedding cache, and the Python process
    still live locally, so we report total system RAM and a reduced
    fixed-component budget (OS + embed + Chroma + Python) without the LLM
    weight line.
    """
    mem: MemoryInfo | None = read_memory_info()
    if mem is None:
        return CheckResult(
            "RAM headroom estimate",
            ok=False,
            detail="cannot read system memory on this platform",
        )
    total_gb: float = mem.total_bytes / (1024 ** 3)
    fixed_cost_gb: float = (
        _RAM_BUDGET_OS_GB
        + _RAM_BUDGET_EMBED_GB
        + _RAM_BUDGET_CHROMA_GB
        + _RAM_BUDGET_PYTHON_GB
    )
    headroom_gb: float = total_gb - fixed_cost_gb
    detail: str = (
        f"total {total_gb:.1f} GB; fixed budget {fixed_cost_gb:.1f} GB "
        f"(cloud LLM — no local weights); headroom ~{headroom_gb:.1f} GB"
    )
    is_ok: bool = total_gb >= 4.0
    if total_gb < 4.0:
        detail += " [BELOW minimum for local ChromaDB + Python process]"
    return CheckResult("RAM headroom estimate", ok=is_ok, detail=detail)
