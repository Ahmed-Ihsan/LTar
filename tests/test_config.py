"""Tests for TM config keys and the Gemma 3 4B model default (task 1)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import AppConfig

pytestmark = pytest.mark.unit


def test_llm_model_default_is_gemma3_4b():
    cfg = AppConfig()
    assert cfg.llm_model == "gemma3:4b"


def test_tm_config_defaults():
    cfg = AppConfig()
    assert cfg.tm_enabled is True
    assert cfg.tm_similarity_threshold == 0.98
    assert cfg.tm_db == "db/tm.sqlite"


def test_tm_threshold_validation_rejects_out_of_range():
    with pytest.raises(ValidationError):
        AppConfig(tm_similarity_threshold=-0.1)
    with pytest.raises(ValidationError):
        AppConfig(tm_similarity_threshold=1.5)


def test_tm_threshold_accepts_boundaries():
    AppConfig(tm_similarity_threshold=0.0)
    AppConfig(tm_similarity_threshold=1.0)
