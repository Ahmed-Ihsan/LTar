"""Tests for the interfaces-layer DTOs (interfaces/models.py).

Covers ``ExcelTranslationReport`` (existing) and the new
``WordTranslationReport`` / ``PdfTranslationReport`` DTOs added by the
``add-pdf-word-translation`` change.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.components.interfaces.models import (
    ExcelTranslationReport,
    PdfTranslationReport,
    WordTranslationReport,
)

pytestmark = pytest.mark.unit


def test_excel_translation_report_is_frozen():
    r = ExcelTranslationReport(
        total_segments=10, translated=8, skipped=1, failed=1,
        cancelled=False, warnings=["w"],
    )
    assert r.translated == 8
    with pytest.raises(FrozenInstanceError):
        r.translated = 9  # type: ignore[misc]


def test_word_translation_report_fields_and_frozen():
    r = WordTranslationReport(
        total_segments=10, translated=8, skipped=1, failed=1,
        cancelled=False, warnings=["w"],
    )
    assert r.total_segments == 10
    assert r.translated == 8
    assert r.skipped == 1
    assert r.failed == 1
    assert r.cancelled is False
    assert r.warnings == ["w"]
    with pytest.raises(FrozenInstanceError):
        r.translated = 9  # type: ignore[misc]


def test_pdf_translation_report_carries_page_count_and_is_frozen():
    r = PdfTranslationReport(
        total_pages=5, total_segments=20, translated=18, skipped=1,
        failed=1, cancelled=False, warnings=[],
    )
    assert r.total_pages == 5
    assert r.total_segments == 20
    assert r.translated == 18
    with pytest.raises(FrozenInstanceError):
        r.total_pages = 6  # type: ignore[misc]
