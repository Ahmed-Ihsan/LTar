"""Tests for TM config keys and the Gemma 3 4B model default (task 1)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import AppConfig, ConfigError, load_config

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


# ---------------------------------------------------------------------------
# Gemini backend config (add-gemini-api-backend)
# ---------------------------------------------------------------------------


def test_llm_backend_defaults_to_ollama():
    cfg = AppConfig()
    assert cfg.llm_backend == "ollama"


def test_llm_backend_accepts_three_valid_values():
    for v in ("ollama", "llamacpp", "gemini"):
        AppConfig(llm_backend=v)  # type: ignore[arg-type]


def test_llm_backend_rejects_unknown_value():
    with pytest.raises(ValidationError):
        AppConfig(llm_backend="openai")  # type: ignore[arg-type]


def test_gemini_fields_default_when_absent():
    cfg = AppConfig()
    assert cfg.gemini_model == "gemini-2.0-flash"
    assert cfg.gemini_embed_model == "text-embedding-004"
    assert cfg.gemini_timeout == 120.0
    assert cfg.gemini_rpm == 15
    assert cfg.gemini_api_key is None


def test_gemini_timeout_validation_rejects_negative():
    with pytest.raises(ValidationError):
        AppConfig(gemini_timeout=-1.0)


def test_gemini_rpm_validation_rejects_non_positive():
    with pytest.raises(ValidationError):
        AppConfig(gemini_rpm=0)
    with pytest.raises(ValidationError):
        AppConfig(gemini_rpm=-5)


def _write_config(tmp_path: Path, body: str) -> Path:
    p: Path = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return p


class TestLoadConfigGeminiKey:
    """`load_config` env-var rules (config spec delta)."""

    def test_gemini_with_valid_env_var_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaTestKey123")
        p = _write_config(tmp_path, "llm_backend: gemini\n")
        cfg = load_config(p)
        assert cfg.llm_backend == "gemini"
        assert cfg.gemini_api_key == "AIzaTestKey123"

    def test_gemini_without_env_var_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        p = _write_config(tmp_path, "llm_backend: gemini\n")
        with pytest.raises(ConfigError):
            load_config(p)

    def test_ollama_without_env_var_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        p = _write_config(tmp_path, "llm_backend: ollama\n")
        cfg = load_config(p)
        assert cfg.llm_backend == "ollama"
        assert cfg.gemini_api_key is None

    def test_key_in_yaml_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaTestKey123")
        p = _write_config(tmp_path, "gemini_api_key: AIzaSecretInYaml\n")
        with pytest.raises(ConfigError):
            load_config(p)

    def test_unknown_backend_raises_with_valid_values_listed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        p = _write_config(tmp_path, "llm_backend: openai\n")
        with pytest.raises(ConfigError) as ei:
            load_config(p)
        msg: str = str(ei.value)
        assert "ollama" in msg
        assert "llamacpp" in msg
        assert "gemini" in msg

    def test_api_key_masked_in_repr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSuperSecretKeyDoNotLeak")
        p = _write_config(tmp_path, "llm_backend: gemini\n")
        cfg = load_config(p)
        r: str = repr(cfg)
        assert "AIzaSuperSecretKeyDoNotLeak" not in r
        assert "***" in r
