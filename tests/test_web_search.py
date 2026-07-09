"""Unit tests for the web_search_node and web search integration.

Tests the ``web_search_node`` in :mod:`src.nodes`:
- Disabled (config off) → no-op pass-through.
- Enabled → searches Iraqi legal sources, populates ``web_search_results``.
- Network error → swallowed, warning appended, pipeline continues.
- Empty input → no search, empty results.

Uses mocked search functions (no real network calls in CI).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.config import AppConfig
from src.components.translation_pipeline.nodes import web_search_node
from src.components.translation_pipeline.models import TranslationState

pytestmark = pytest.mark.unit


def _state(
    input_text: str = "According to Article 6 of the Civil Procedure Code.",
) -> TranslationState:
    return {
        "input_text": input_text,
        "direction": "en-ar",
        "glossary_hits": [],
        "context_chunks": [],
        "tm_hits": [],
        "web_search_results": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
    }


def _cfg(enabled: bool = True) -> AppConfig:
    cfg: AppConfig = AppConfig()
    cfg.web_search_enabled = enabled
    cfg.web_search_max_results = 3
    return cfg


# ---------------------------------------------------------------------------
# 1. Disabled (config off) — no-op pass-through
# ---------------------------------------------------------------------------


class TestWebSearchDisabled:
    def test_disabled_returns_empty_results(self) -> None:
        cfg: AppConfig = _cfg(enabled=False)
        state: TranslationState = _state()
        result: TranslationState = web_search_node(state, cfg=cfg)
        assert result["web_search_results"] == []

    def test_disabled_does_not_call_search(self) -> None:
        cfg: AppConfig = _cfg(enabled=False)
        state: TranslationState = _state()
        with patch("src.components.knowledge_sources.legal_search.search_all_sources") as mock_search:
            web_search_node(state, cfg=cfg)
            mock_search.assert_not_called()

    def test_disabled_preserves_state(self) -> None:
        cfg: AppConfig = _cfg(enabled=False)
        state: TranslationState = _state()
        result: TranslationState = web_search_node(state, cfg=cfg)
        assert result["input_text"] == state["input_text"]
        assert result["direction"] == state["direction"]


# ---------------------------------------------------------------------------
# 2. Enabled — searches and populates results
# ---------------------------------------------------------------------------


class TestWebSearchEnabled:
    @patch("src.components.translation_pipeline.nodes.search_all_sources")
    def test_enabled_populates_results(self, mock_search) -> None:
        from src.components.knowledge_sources.legal_search import SearchHit

        mock_search.return_value = [
            SearchHit(
                title="Iraqi Civil Procedure Code",
                url="https://moj.gov.iq/view.123/",
                snippet="قانون المرافعات المدنية",
                source="Iraq MoJ",
            ),
        ]
        cfg: AppConfig = _cfg(enabled=True)
        state: TranslationState = _state()
        result: TranslationState = web_search_node(state, cfg=cfg)
        assert len(result["web_search_results"]) == 1
        assert result["web_search_results"][0]["title"] == "Iraqi Civil Procedure Code"
        assert result["web_search_results"][0]["source"] == "Iraq MoJ"

    @patch("src.components.translation_pipeline.nodes.search_all_sources")
    def test_enabled_passes_max_results_from_config(self, mock_search) -> None:
        mock_search.return_value = []
        cfg: AppConfig = _cfg(enabled=True)
        cfg.web_search_max_results = 7
        state: TranslationState = _state()
        web_search_node(state, cfg=cfg)
        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs["max_results_per_source"] == 7

    @patch("src.components.translation_pipeline.nodes.search_all_sources")
    def test_enabled_uses_input_text_as_query(self, mock_search) -> None:
        mock_search.return_value = []
        cfg: AppConfig = _cfg(enabled=True)
        state: TranslationState = _state(input_text="Custom legal query text")
        web_search_node(state, cfg=cfg)
        mock_search.assert_called_once_with(
            "Custom legal query text", max_results_per_source=3
        )


# ---------------------------------------------------------------------------
# 3. Error handling — network failures swallowed
# ---------------------------------------------------------------------------


class TestWebSearchErrorHandling:
    @patch("src.components.translation_pipeline.nodes.search_all_sources")
    def test_network_error_returns_empty_with_warning(self, mock_search) -> None:
        mock_search.side_effect = Exception("Network error")
        cfg: AppConfig = _cfg(enabled=True)
        state: TranslationState = _state()
        result: TranslationState = web_search_node(state, cfg=cfg)
        assert result["web_search_results"] == []
        assert any("web search" in w.lower() for w in result["warnings"])

    @patch("src.components.translation_pipeline.nodes.search_all_sources")
    def test_no_results_appends_warning(self, mock_search) -> None:
        mock_search.return_value = []
        cfg: AppConfig = _cfg(enabled=True)
        state: TranslationState = _state()
        result: TranslationState = web_search_node(state, cfg=cfg)
        assert result["web_search_results"] == []
        assert any("no results" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# 4. Edge cases
# ---------------------------------------------------------------------------


class TestWebSearchEdgeCases:
    def test_empty_input_returns_empty(self) -> None:
        cfg: AppConfig = _cfg(enabled=True)
        state: TranslationState = _state(input_text="   ")
        with patch("src.components.knowledge_sources.legal_search.search_all_sources") as mock_search:
            result: TranslationState = web_search_node(state, cfg=cfg)
            assert result["web_search_results"] == []
            mock_search.assert_not_called()

    @patch("src.components.translation_pipeline.nodes.search_all_sources")
    def test_preserves_existing_warnings(self, mock_search) -> None:
        mock_search.return_value = []
        cfg: AppConfig = _cfg(enabled=True)
        state: TranslationState = _state()
        state["warnings"] = ["Existing warning"]
        result: TranslationState = web_search_node(state, cfg=cfg)
        assert "Existing warning" in result["warnings"]
        assert len(result["warnings"]) == 2
