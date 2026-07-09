"""Tests for the TM routing decision function (task 4)."""
from __future__ import annotations

import pytest

from src.components.translation_pipeline.decision import route_tm
from src.components.translation_pipeline.models import TmHit

pytestmark = pytest.mark.unit


def test_route_tm_none_hit_returns_false():
    assert route_tm(None, threshold=0.98) is False


def test_route_tm_above_threshold_returns_true():
    hit: TmHit = {
        "source_sentence": "test", "target_sentence": "اختبار",
        "similarity": 0.99, "char_start": 0, "char_end": 4,
    }
    assert route_tm(hit, threshold=0.98) is True


def test_route_tm_at_threshold_returns_true():
    hit: TmHit = {
        "source_sentence": "test", "target_sentence": "اختبار",
        "similarity": 0.98, "char_start": 0, "char_end": 4,
    }
    assert route_tm(hit, threshold=0.98) is True


def test_route_tm_below_threshold_returns_false():
    hit: TmHit = {
        "source_sentence": "test", "target_sentence": "اختبار",
        "similarity": 0.97, "char_start": 0, "char_end": 4,
    }
    assert route_tm(hit, threshold=0.98) is False
