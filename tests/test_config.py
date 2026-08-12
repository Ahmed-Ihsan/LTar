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


# ---------------------------------------------------------------------------
# WordConfig / PdfConfig (add-pdf-word-translation)
# ---------------------------------------------------------------------------


def test_word_config_defaults_applied_when_absent():
    cfg = AppConfig()
    assert cfg.word.translate_comments is True
    assert cfg.word.translate_headers_footers is True
    assert cfg.word.translate_footnotes is True
    assert cfg.word.translate_endnotes is True
    assert cfg.word.translate_glossary_doc is False
    assert cfg.word.max_segment_chars == 8192
    assert cfg.word.max_docx_bytes == 50 * 1024 * 1024
    assert cfg.word.max_segments == 20000


def test_word_config_honors_explicit_overrides():
    cfg = AppConfig(word={"translate_comments": False, "max_segment_chars": 1024})
    assert cfg.word.translate_comments is False
    assert cfg.word.max_segment_chars == 1024
    # Untouched fields retain defaults.
    assert cfg.word.translate_headers_footers is True


def test_word_config_rejects_max_segment_chars_below_16():
    with pytest.raises(ValidationError):
        AppConfig(word={"max_segment_chars": 8})


def test_word_config_rejects_max_docx_bytes_below_1_mib():
    with pytest.raises(ValidationError):
        AppConfig(word={"max_docx_bytes": 1024})


def test_word_config_rejects_max_segments_below_100():
    with pytest.raises(ValidationError):
        AppConfig(word={"max_segments": 10})


def test_word_config_set_bidi_direction_default_true() -> None:
    from src.config.models import WordConfig
    cfg = WordConfig()
    assert cfg.set_bidi_direction is True


def test_word_config_set_bidi_direction_override_false() -> None:
    from src.config.models import WordConfig
    cfg = WordConfig(set_bidi_direction=False)
    assert cfg.set_bidi_direction is False


def test_pdf_config_defaults_applied_when_absent():
    cfg = AppConfig()
    assert cfg.pdf.out_format == "docx"
    assert cfg.pdf.max_pdf_bytes == 100 * 1024 * 1024
    assert cfg.pdf.max_pages == 500
    assert cfg.pdf.max_segment_chars == 8192
    assert cfg.pdf.max_segments == 20000
    assert cfg.pdf.skip_header_footer is True


def test_pdf_config_honors_explicit_overrides():
    cfg = AppConfig(pdf={"out_format": "txt", "max_pages": 50})
    assert cfg.pdf.out_format == "txt"
    assert cfg.pdf.max_pages == 50
    assert cfg.pdf.skip_header_footer is True  # untouched


def test_pdf_config_rejects_invalid_out_format():
    with pytest.raises(ValidationError):
        AppConfig(pdf={"out_format": "rtf"})  # type: ignore[arg-type]


def test_pdf_config_rejects_max_pdf_bytes_below_1_mib():
    with pytest.raises(ValidationError):
        AppConfig(pdf={"max_pdf_bytes": 1024})


def test_pdf_config_rejects_non_positive_max_pages():
    with pytest.raises(ValidationError):
        AppConfig(pdf={"max_pages": 0})


def test_load_config_applies_word_pdf_defaults_when_sections_absent(tmp_path: Path):
    p = _write_config(tmp_path, "llm_backend: ollama\n")
    cfg = load_config(p)
    assert cfg.word.translate_comments is True
    assert cfg.pdf.out_format == "docx"


def test_load_config_honors_explicit_word_pdf_sections(tmp_path: Path):
    p = _write_config(
        tmp_path,
        "llm_backend: ollama\n"
        "word:\n  translate_comments: false\n  max_segment_chars: 2048\n"
        "pdf:\n  out_format: txt\n  max_pages: 25\n",
    )
    cfg = load_config(p)
    assert cfg.word.translate_comments is False
    assert cfg.word.max_segment_chars == 2048
    assert cfg.pdf.out_format == "txt"
    assert cfg.pdf.max_pages == 25


# ---------------------------------------------------------------------------
# ollama_num_ctx (add-ollama-num-ctx-config)
# ---------------------------------------------------------------------------


def test_ollama_num_ctx_default_is_2048():
    cfg = AppConfig()
    assert cfg.ollama_num_ctx == 2048


def test_ollama_num_ctx_accepts_custom_value():
    cfg = AppConfig(ollama_num_ctx=4096)
    assert cfg.ollama_num_ctx == 4096


def test_ollama_num_ctx_rejects_zero():
    with pytest.raises(ValidationError):
        AppConfig(ollama_num_ctx=0)


def test_ollama_num_ctx_rejects_negative():
    with pytest.raises(ValidationError):
        AppConfig(ollama_num_ctx=-1024)


def test_load_config_ollama_num_ctx_override(tmp_path: Path):
    p = _write_config(tmp_path, "ollama_num_ctx: 8192\n")
    cfg = load_config(p)
    assert cfg.ollama_num_ctx == 8192


def test_load_config_ollama_num_ctx_default_when_absent(tmp_path: Path):
    p = _write_config(tmp_path, "llm_backend: ollama\n")
    cfg = load_config(p)
    assert cfg.ollama_num_ctx == 2048

