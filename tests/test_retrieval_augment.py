"""Tests for EN→AR retrieval query augmentation (nodes helper).

The RAG corpus is predominantly Arabic, so an English query embeds poorly
against it. For EN→AR, the glossary-bound Arabic target terms are appended to
the retrieval query as anchors so the Arabic corpus returns relevant chunks.
AR→EN is left unchanged (already monolingual Arabic→Arabic).
"""
from __future__ import annotations

import pytest

from src.components.translation_pipeline.nodes import _augment_query_for_retrieval

pytestmark = pytest.mark.unit


def _hit(source: str, target: str) -> dict:
    return {
        "source_term": source,
        "target_term": target,
        "law_ref": "L",
        "article_ref": "",
        "note": "",
        "char_start": 0,
        "char_end": 0,
    }


class TestAugmentQuery:
    def test_en_ar_appends_arabic_anchors(self) -> None:
        hits = [_hit("contract of sale", "عقد البيع"),
                _hit("Court of First Instance", "محكمة البداية")]
        q = _augment_query_for_retrieval(
            "The contract of sale was filed.", "en", "ar", hits,
        )
        assert "The contract of sale was filed." in q
        assert "عقد البيع" in q
        assert "محكمة البداية" in q

    def test_ar_en_unchanged(self) -> None:
        # AR→EN retrieval is already monolingual; do not augment.
        hits = [_hit("عقد البيع", "contract of sale")]
        q = _augment_query_for_retrieval("هذا عقد البيع", "ar", "en", hits)
        assert q == "هذا عقد البيع"

    def test_no_hits_unchanged(self) -> None:
        q = _augment_query_for_retrieval("some English text", "en", "ar", [])
        assert q == "some English text"

    def test_empty_target_terms_unchanged(self) -> None:
        hits = [_hit("contract", "")]
        q = _augment_query_for_retrieval("a contract here", "en", "ar", hits)
        assert q == "a contract here"
