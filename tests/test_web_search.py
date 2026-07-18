"""Unit tests for the web_search_node and web search integration.

Tests the ``web_search_node`` in :mod:`src.components.translation_pipeline.nodes`:
- Disabled (searcher=None) → no-op pass-through.
- Enabled → searches Iraqi legal sources, populates ``web_search_results``.
- Network error → swallowed, warning appended, pipeline continues.
- Empty input → no search, empty results.

Uses a fake ``WebSearcher`` protocol implementation (no real network calls in CI).
"""
from __future__ import annotations

import httpx
import pytest

from src.components.translation_pipeline.models import TranslationState, WebSearchResult
from src.components.translation_pipeline.nodes import web_search_node
from src.config import AppConfig

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


def _cfg() -> AppConfig:
    cfg: AppConfig = AppConfig()
    cfg.web_search_enabled = True
    cfg.web_search_max_results = 3
    return cfg


class _FakeSearcher:
    """Fake WebSearcher for testing — records calls and returns canned results."""

    def __init__(
        self,
        results: list[WebSearchResult] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._results: list[WebSearchResult] = results or []
        self._raise: Exception | None = raise_exc
        self.calls: list[str] = []

    def search(self, query: str) -> list[WebSearchResult]:
        self.calls.append(query)
        if self._raise is not None:
            raise self._raise
        return list(self._results)


# ---------------------------------------------------------------------------
# 1. Disabled (searcher=None) — no-op pass-through
# ---------------------------------------------------------------------------


class TestWebSearchDisabled:
    def test_disabled_returns_empty_results(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        result: TranslationState = web_search_node(state, cfg=cfg, searcher=None)
        assert result["web_search_results"] == []

    def test_disabled_does_not_call_search(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        searcher: _FakeSearcher = _FakeSearcher()
        web_search_node(state, cfg=cfg, searcher=None)
        assert searcher.calls == []

    def test_disabled_preserves_state(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        result: TranslationState = web_search_node(state, cfg=cfg, searcher=None)
        assert result["input_text"] == state["input_text"]
        assert result["direction"] == state["direction"]


# ---------------------------------------------------------------------------
# 2. Enabled — searches and populates results
# ---------------------------------------------------------------------------


class TestWebSearchEnabled:
    def test_enabled_populates_results(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        searcher: _FakeSearcher = _FakeSearcher([
            WebSearchResult(
                title="Iraqi Civil Procedure Code",
                url="https://moj.gov.iq/view.123/",
                snippet="قانون المرافعات المدنية",
                source="Iraq MoJ",
            ),
        ])
        result: TranslationState = web_search_node(state, cfg=cfg, searcher=searcher)
        assert len(result["web_search_results"]) == 1
        assert result["web_search_results"][0]["title"] == "Iraqi Civil Procedure Code"
        assert result["web_search_results"][0]["source"] == "Iraq MoJ"

    def test_enabled_uses_input_text_as_query(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state(input_text="Custom legal query text")
        searcher: _FakeSearcher = _FakeSearcher()
        web_search_node(state, cfg=cfg, searcher=searcher)
        assert searcher.calls == ["Custom legal query text"]


class TestWebSearcherAdapter:
    def test_adapter_passes_max_results_to_concrete_function(self) -> None:
        from unittest.mock import patch

        from src.components.translation_pipeline.adapters import WebSearcherAdapter

        with patch(
            "src.components.translation_pipeline.adapters.search_all_sources"
        ) as mock_search:
            mock_search.return_value = []
            adapter = WebSearcherAdapter(max_results_per_source=7)
            adapter.search("test query")
            mock_search.assert_called_once_with(
                "test query", max_results_per_source=7
            )


# ---------------------------------------------------------------------------
# 3. Error handling — network failures swallowed
# ---------------------------------------------------------------------------


class TestWebSearchErrorHandling:
    def test_network_error_returns_empty_with_warning(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        searcher: _FakeSearcher = _FakeSearcher(raise_exc=httpx.HTTPError("Network error"))
        result: TranslationState = web_search_node(state, cfg=cfg, searcher=searcher)
        assert result["web_search_results"] == []
        assert any("web search" in w.lower() for w in result["warnings"])

    def test_no_results_appends_warning(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        searcher: _FakeSearcher = _FakeSearcher(results=[])
        result: TranslationState = web_search_node(state, cfg=cfg, searcher=searcher)
        assert result["web_search_results"] == []
        assert any("no results" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# 4. Edge cases
# ---------------------------------------------------------------------------


class TestWebSearchEdgeCases:
    def test_empty_input_returns_empty(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state(input_text="   ")
        searcher: _FakeSearcher = _FakeSearcher()
        result: TranslationState = web_search_node(state, cfg=cfg, searcher=searcher)
        assert result["web_search_results"] == []
        assert searcher.calls == []

    def test_preserves_existing_warnings(self) -> None:
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        state["warnings"] = ["Existing warning"]
        searcher: _FakeSearcher = _FakeSearcher(results=[])
        result: TranslationState = web_search_node(state, cfg=cfg, searcher=searcher)
        assert "Existing warning" in result["warnings"]
        assert len(result["warnings"]) == 2


# ---------------------------------------------------------------------------
# Task 4.7 — narrowed exception + logger.warning tests
# ---------------------------------------------------------------------------


class TestWebSearchNarrowedExceptions:
    def test_httpx_error_logs_warning(self, caplog) -> None:
        """httpx.HTTPError is caught and logged."""
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        searcher: _FakeSearcher = _FakeSearcher(
            raise_exc=httpx.ConnectError("connection refused")
        )
        with caplog.at_level("WARNING", logger="src.components.translation_pipeline.nodes"):
            result: TranslationState = web_search_node(state, cfg=cfg, searcher=searcher)
        assert result["web_search_results"] == []
        assert any("web_search failed" in r.message for r in caplog.records)

    def test_value_error_logs_warning(self, caplog) -> None:
        """ValueError is caught and logged."""
        cfg: AppConfig = _cfg()
        state: TranslationState = _state()
        searcher: _FakeSearcher = _FakeSearcher(raise_exc=ValueError("bad query"))
        with caplog.at_level("WARNING", logger="src.components.translation_pipeline.nodes"):
            result: TranslationState = web_search_node(state, cfg=cfg, searcher=searcher)
        assert result["web_search_results"] == []
        assert any("web_search failed" in r.message for r in caplog.records)
