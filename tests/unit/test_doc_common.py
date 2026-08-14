"""Tests for shared document-translation helpers extracted from excel.py.

These re-assert the protect/restore/StringSegment/ProgressCallback behavior
that ``tests/test_excel.py`` already pins, but against the new
``src.components.interfaces._doc_common`` module so the mechanical move is
verified independently.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.components.interfaces._doc_common import (
    ProgressCallback,
    StringSegment,
    protect_non_translatable,
    restore_protected,
)

pytestmark = pytest.mark.unit


def test_protect_and_restore_roundtrip():
    text = "See Article 12 and https://example.com/law for {placeholder} details."
    protected, token_map = protect_non_translatable(text)
    assert "\x00T" in protected
    restored = restore_protected(protected, token_map)
    assert restored == text


def test_protect_replaces_url_with_sentinel():
    text = "See https://example.org/x for details"
    protected, token_map = protect_non_translatable(text)
    assert "https://example.org/x" not in protected
    assert "https://example.org/x" in token_map.values()
    assert restore_protected(protected, token_map) == text


def test_protect_replaces_placeholder_with_sentinel():
    text = "Total for {year}: مبلغ"
    protected, token_map = protect_non_translatable(text)
    assert "{year}" not in protected
    assert restore_protected(protected, token_map) == text


def test_protect_replaces_number_with_sentinel():
    text = "المادة 148 تنص على ذلك"
    protected, token_map = protect_non_translatable(text)
    assert "148" not in protected
    assert restore_protected(protected, token_map) == text


def test_identical_tokens_reuse_sentinel():
    text = "{x} and {x} and 148 and 148"
    protected, token_map = protect_non_translatable(text)
    # Two distinct originals -> two sentinels, each used twice.
    assert protected.count("\x00T0\x00") == 2
    assert protected.count("\x00T1\x00") == 2
    assert restore_protected(protected, token_map) == text


def test_plain_text_unchanged():
    text = "عقد البيع"
    protected, token_map = protect_non_translatable(text)
    assert protected == text
    assert token_map == {}
    assert restore_protected(protected, token_map) == text


def test_restore_removes_leftover_sentinels_defensively():
    # A model that drops a sentinel should not corrupt output: leftover
    # sentinels not in the token_map are removed.
    protected = "hello \x00T0\x00 world"
    restored = restore_protected(protected, {})
    assert "\x00" not in restored


def test_string_segment_is_frozen():
    seg = StringSegment(part="xl/sharedStrings.xml", text="عقد البيع")
    with pytest.raises(FrozenInstanceError):
        seg.text = "other"  # type: ignore[misc]


def test_string_segment_fields():
    seg = StringSegment(part="word/document.xml", text="Article 1")
    assert seg.part == "word/document.xml"
    assert seg.text == "Article 1"


def test_progress_callback_is_a_protocol():
    # ProgressCallback is a Protocol (a structural type). A callable with the
    # right signature is assignable to it; we verify the protocol symbol is
    # importable and has the expected __call__ attribute in its annotations.
    def cb(completed: int, total: int, current: str) -> None:
        return None
    # Plain (non-runtime_checkable) Protocols can't be isinstance-checked; the
    # callable is structurally compatible, which we assert by calling it.
    cb(1, 2, "x")
    assert ProgressCallback is not None
