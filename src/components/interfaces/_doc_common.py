"""Shared helpers for document-translation adapters (excel, word, pdf).

This module owns the pieces that are not specific to any one document format:

- :class:`StringSegment` — one translatable text occurrence (a zip part path
  or PDF page identifier + the source text). Deduplicated by ``text`` so each
  unique source string is translated exactly once.
- :class:`ProgressCallback` — structural protocol for per-segment progress
  reporting: ``(completed, total, current_source) -> None``.
- :func:`protect_non_translatable` / :func:`restore_protected` — replace
  non-translatable tokens (URLs, emails, numbers, ``{...}`` / ``<...>`` /
  ``%...%`` placeholders, Excel header/footer ``&``-codes) with stable
  ``\\x00TN\\x00`` sentinels before translation and restore them verbatim
  after. Guarantees formulas-as-text, placeholders, IDs, and numbers are not
  altered by the LLM.
- :func:`_translate_segment` — the per-segment protect → ``run_translation``
  → restore loop shared by the excel, word, and pdf orchestrators. Returns
  the translated text or ``None`` on ``LLMRuntimeError`` / ``EmbeddingError``
  (the caller records the warning and preserves the original text).

These helpers have **no dependency on the pipeline or adapters** at module
import time — :func:`_translate_segment` receives ``run_translation_fn`` and
the adapters as keyword-only arguments (DIP), so the module stays unit-
testable without Ollama and respects the acyclic component dependency graph
(``interfaces → translation_pipeline``, never the reverse).

Extracted from :mod:`src.components.interfaces.excel` by the
``add-pdf-word-translation`` change so the new ``word.py`` and ``pdf.py``
adapters can reuse them. ``excel.py`` re-imports every symbol below and
keeps them in its ``__all__`` for backward compatibility.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

import typer

from src.components.infrastructure.embeddings import EmbeddingAdapter
from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.infrastructure.run_logging import RunLogger
from src.components.knowledge_sources.glossary import GlossaryIndex
from src.components.knowledge_sources.tm import TranslationMemory
from src.components.translation_pipeline.exceptions import (
    EmbeddingError,
    LLMRuntimeError,
)
from src.config import AppConfig

if TYPE_CHECKING:
    from src.components.interfaces.models import Adapters

__all__ = [
    "DocumentReport",
    "ProgressCallback",
    "StringSegment",
    "protect_non_translatable",
    "render_document_report",
    "restore_protected",
    "run_document_command",
    "translate_segment",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class StringSegment:
    """One translatable text occurrence in a document part.

    ``part`` is the ZIP entry path (e.g. ``xl/sharedStrings.xml`` or
    ``word/document.xml``) or, for PDF, a page identifier. ``text`` is the
    source text. Segments are deduplicated by ``text`` so each unique source
    string is translated exactly once; ``part`` is retained for reporting
    and debugging.
    """

    part: str
    text: str


# ---------------------------------------------------------------------------
# Non-translatable token protection
# ---------------------------------------------------------------------------

# Sentinel format: control-character-delimited so it never collides with real
# legal text and is passed through verbatim by local LLM tokenizers.
_SENTINEL_OPEN: str = "\x00T"
_SENTINEL_CLOSE: str = "\x00"
_SENTINEL_RE: re.Pattern[str] = re.compile(r"\x00T(\d+)\x00")

# Protection patterns, applied in order. URLs first (so embedded numbers/emails
# are not separately protected), then emails, template placeholders, Excel
# header/footer ``&``-codes, and finally standalone numbers.
_PROTECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://[^\s<>\"']+"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\$\{[^}]+\}"),
    re.compile(r"\{[^}]+\}"),
    re.compile(r"<[A-Za-z_][\w.-]*>"),
    re.compile(r"%[A-Za-z_][\w]*%"),
    re.compile(r"&[A-Za-z0-9\"&]"),
    re.compile(r"(?<![\w/])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w/])"),
)


def protect_non_translatable(
    text: str,
) -> tuple[str, dict[str, str]]:
    """Replace non-translatable tokens with stable sentinels.

    Returns ``(protected_text, token_map)`` where ``token_map`` maps each
    sentinel to its original token. Identical originals reuse the same sentinel
    so the protected text stays short.
    """
    token_map: dict[str, str] = {}
    original_to_sentinel: dict[str, str] = {}

    def _replace(match: re.Match[str]) -> str:
        original: str = match.group(0)
        sentinel = original_to_sentinel.get(original)
        if sentinel is None:
            sentinel = f"{_SENTINEL_OPEN}{len(token_map)}{_SENTINEL_CLOSE}"
            original_to_sentinel[original] = sentinel
            token_map[sentinel] = original
        return sentinel

    protected: str = text
    for pattern in _PROTECTION_PATTERNS:
        protected = pattern.sub(_replace, protected)
    return protected, token_map


def restore_protected(text: str, token_map: dict[str, str]) -> str:
    """Restore sentinels to their original tokens.

    Any leftover sentinel not in ``token_map`` is removed (defensive: a model
    that drops a sentinel should not corrupt the output).
    """
    def _restore(match: re.Match[str]) -> str:
        return token_map.get(match.group(0), "")

    return _SENTINEL_RE.sub(_restore, text)


# ---------------------------------------------------------------------------
# Progress callback protocol
# ---------------------------------------------------------------------------


class ProgressCallback(Protocol):
    """Progress callback signature: ``(completed, total, current_source)``."""

    def __call__(self, completed: int, total: int, current: str) -> None: ...


# ---------------------------------------------------------------------------
# Per-segment translation loop (shared by excel / word / pdf orchestrators)
# ---------------------------------------------------------------------------


def translate_segment(
    source: str,
    seg: StringSegment,
    direction: str,
    cfg: AppConfig,
    *,
    run_translation_fn: Callable[..., Any],
    llm: LLMEngineAdapter,
    embedder: EmbeddingAdapter,
    glossary_index: GlossaryIndex | None,
    persist_dir: str | None,
    run_logger: RunLogger | None,
    tm: TranslationMemory | None,
) -> str | None:
    """Translate one segment; return the translated text or ``None`` on failure.

    Protects non-translatable tokens, calls ``run_translation_fn``, restores
    the tokens, and returns the result. Returns ``None`` if the translation
    failed (``LLMRuntimeError`` / ``EmbeddingError``) or produced empty output;
    the caller records the warning and preserves the original text.

    The ``seg`` argument is retained for reporting/debugging symmetry with
    :class:`StringSegment`; the translation itself only uses ``source``.
    """
    _ = seg  # retained for symmetry; the translation uses `source` only
    protected, token_map = protect_non_translatable(source)
    try:
        state = run_translation_fn(
            protected, direction, cfg,
            llm=llm, embedder=embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
            run_logger=run_logger, tm=tm,
        )
    except (LLMRuntimeError, EmbeddingError):
        return None
    raw: str = state.get("final_output") or ""
    restored: str = restore_protected(raw, token_map) if raw else source
    if not restored.strip():
        return None
    return restored


# ---------------------------------------------------------------------------
# CLI command orchestration (shared by the excel / word / pdf commands)
# ---------------------------------------------------------------------------


class DocumentReport(Protocol):
    """Common shape of Excel/Word/PDF translation reports.

    The three concrete reports (:class:`ExcelTranslationReport`,
    :class:`WordTranslationReport`, :class:`PdfTranslationReport`) all carry
    these fields as frozen-dataclass attributes (read-only). Members are
    declared as read-only properties so frozen dataclasses satisfy the
    protocol. :class:`PdfTranslationReport` additionally has ``total_pages``;
    the success-message formatting that uses it stays in the individual command
    so this protocol only models the shared portion.
    """

    @property
    def total_segments(self) -> int: ...

    @property
    def translated(self) -> int: ...

    @property
    def skipped(self) -> int: ...

    @property
    def failed(self) -> int: ...

    @property
    def cancelled(self) -> bool: ...

    @property
    def warnings(self) -> list[str]: ...


ReportT = TypeVar("ReportT")


def run_document_command(
    input_arg: Path,
    out: Path,
    expected_suffix: str,
    config_path: Path,
    direction: str,
    translate_fn: Callable[..., ReportT],
    *,
    suffix_article: str = "a",
) -> ReportT:
    """Validate inputs, load config, build adapters, and run a document translation.

    Shared by the ``pdf``, ``word``, and ``excel`` CLI commands. Performs the
    common pre-flight validation (file existence, extension check, path
    containment), loads the config, constructs adapters, and calls
    ``translate_fn`` inside a ``try/finally`` that closes the translation
    memory. Returns the translation report for the caller to render via
    :func:`render_document_report`.

    ``suffix_article`` is the grammatical article (``"a"`` or ``"an"``) used in
    the extension-mismatch error message so it reads naturally for each format
    (e.g. "a .pdf file" vs "an .xlsx file").

    The ``cli`` module is imported lazily inside the function body to avoid a
    circular import (``cli`` imports the command sub-package which imports this
    module).
    """
    from src.components.interfaces import cli as _cli

    if not input_arg.is_file():
        typer.secho(
            f"input file not found: {input_arg}", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)
    if input_arg.suffix.lower() != expected_suffix:
        typer.secho(
            f"input must be {suffix_article} {expected_suffix} file, "
            f"got: {input_arg.suffix}",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    cfg = _cli.load_or_exit(config_path)

    root: Path = _cli._project_root(cfg)
    _cli.validate_path_in_root(input_arg, root)
    _cli.validate_path_in_root(out, root)

    adapters: Adapters = _cli._construct_adapters(cfg)

    try:
        with _cli._new_run_logger(cfg) as run_logger:
            report = translate_fn(
                str(input_arg), str(out), direction, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index,
                persist_dir=adapters.persist_dir,
                run_logger=run_logger,
                tm=adapters.tm,
            )
    finally:
        if adapters.tm is not None:
            adapters.tm.close()

    return report


def render_document_report(
    report: DocumentReport,
    success_message: str,
) -> None:
    """Render a document translation report to stdout.

    Prints the ``success_message`` (green) followed by the standard
    failed / skipped / cancelled / warnings lines (yellow). The success line is
    passed in by the caller because it differs per format (the ``pdf`` command
    includes a page count that the others do not).
    """
    typer.secho(success_message, fg=typer.colors.GREEN)
    if report.failed:
        typer.secho(
            f"  {report.failed} segment(s) failed (original text preserved).",
            fg=typer.colors.YELLOW,
        )
    if report.skipped:
        typer.secho(
            f"  {report.skipped} segment(s) skipped.", fg=typer.colors.YELLOW,
        )
    if report.cancelled:
        typer.secho("  run was cancelled.", fg=typer.colors.YELLOW)
    for w in report.warnings:
        typer.secho(f"  warning: {w}", fg=typer.colors.YELLOW)
