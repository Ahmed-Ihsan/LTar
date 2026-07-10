"""Unit tests for the Iraqi legal search MCP server.

Tests the search tool implementations with mocked HTTP responses (no real
network calls in CI). Verifies HTML parsing, result extraction, and edge
cases (empty query, network error, malformed HTML).
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.components.knowledge_sources.legal_search import (
    SearchHit,
)
from src.components.knowledge_sources.legal_search import (
    search_dijlex as _search_dijlex_impl,
)
from src.components.knowledge_sources.legal_search import (
    search_moj as _search_moj_impl,
)
from src.components.knowledge_sources.legal_search import (
    search_national_library as _search_national_library_impl,
)
from src.components.knowledge_sources.legal_search import (
    search_ur_portal as _search_ur_portal_impl,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock HTML fixtures (based on real page structures)
# ---------------------------------------------------------------------------


# MoJ: POST search returns links with /view.XXXX/ hrefs.
# Law results have "قانون" or "Law" in text; news results don't.
_MOJ_HTML = """
<html><body>
<a href="/view.10372/">Law of the National Authority of the Nuclear,Radioactive,Chemical</a>
<a href="/view.10372/">قانون الهيأة الوطنية للرقابة النووية والاشعاعية والكيميائية</a>
<a href="/view.10372/">التفاصيل</a>
<a href="/view.10370/">Iraqi Atomic Energy Authority Law No.(43) of 2016</a>
<a href="/view.10370/">قانون هيئة الطاقة الذرية العراقية</a>
<a href="/view.10376/">News article about prison rehabilitation program</a>
<a href="/view.10376/">التفاصيل</a>
<a href="/view.10362/">وزارة العدل تكسب دعوى قضائية</a>
</body></html>
"""

# NLA: Results are <a> tags with href='fullrecr.php?nid=...' and text
# format "author--title--year--type".
_NLA_HTML = (
    '<html><body><ul>'
    '<li><a href="fullrecr.php?nid=16109&hl=ara">'
    'author1--title1--1984--k</a></li>'
    '<li><a href="fullrecr.php?nid=27908&hl=ara">'
    'author2--title2--1966--k</a></li>'
    '<li><a href="fullrecr.php?nid=35035&hl=ara">'
    'author3--title3--1980--k</a></li>'
    '</ul></body></html>'
)

# UR Portal: Vue.js SPA with JSON-LD structured data.
_UR_HTML = """
<html><body>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "GovernmentOrganization",
 "name": "وزارة العدل", "url": "https://moj.gov.iq"}
</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "GovernmentOrganization",
 "name": "وزارة المالية", "url": "https://mof.gov.iq"}
</script>
<a href="/index/about-us">About Us</a>
</body></html>
"""

# UR Portal: no data (Vue.js SPA without JSON-LD).
_UR_EMPTY_HTML = """
<html><body>
<div class="all-orgs">عذراً، لاتوجد بيانات تطابق طلبك</div>
</body></html>
"""

_EMPTY_HTML = "<html><body></body></html>"


# ---------------------------------------------------------------------------
# 1. Dijlex search
# ---------------------------------------------------------------------------


class TestSearchDijlex:
    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_returns_cloudflare_notice_on_403(self, mock_fetch) -> None:
        """Dijlex is behind Cloudflare — 403 returns a notice, not empty."""
        mock_fetch.return_value = ""
        hits: list[SearchHit] = _search_dijlex_impl("قانون")
        assert len(hits) == 1
        assert "Cloudflare" in hits[0].title or "403" in hits[0].title
        assert hits[0].source == "Dijlex"

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_parses_results_when_html_available(self, mock_fetch) -> None:
        mock_fetch.return_value = (
            '<html><body><div class="search-result">'
            '<h3><a href="/law/123">قانون المرافعات المدنية</a></h3>'
            '<p class="snippet">قانون ينظم أصول المحاكمات</p>'
            "</div></body></html>"
        )
        hits: list[SearchHit] = _search_dijlex_impl("المرافعات")
        assert len(hits) == 1
        assert "قانون المرافعات" in hits[0].title

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_empty_query_returns_empty(self, mock_fetch) -> None:
        hits: list[SearchHit] = _search_dijlex_impl("")
        assert hits == []
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Ministry of Justice search
# ---------------------------------------------------------------------------


class TestSearchMoj:
    @patch("src.components.knowledge_sources.legal_search._post_html")
    def test_parses_law_results(self, mock_post) -> None:
        """MoJ POST search returns law links with /view. hrefs."""
        mock_post.return_value = _MOJ_HTML
        hits: list[SearchHit] = _search_moj_impl("قانون")
        # Should find 2 unique laws (10372 and 10370), not news articles.
        assert len(hits) == 2
        urls: list[str] = [h.url for h in hits]
        assert "https://moj.gov.iq/view.10372/" in urls
        assert "https://moj.gov.iq/view.10370/" in urls
        assert hits[0].source == "Iraq MoJ"

    @patch("src.components.knowledge_sources.legal_search._post_html")
    def test_deduplicates_by_url(self, mock_post) -> None:
        """Arabic + English titles for the same law share a URL."""
        mock_post.return_value = _MOJ_HTML
        hits: list[SearchHit] = _search_moj_impl("قانون")
        # Law 10372 appears twice (AR + EN) but should be one hit with
        # the alternate title in the snippet.
        law_10372 = [h for h in hits if "10372" in h.url]
        assert len(law_10372) == 1
        # The snippet should contain the alternate-language title.
        assert "قانون" in law_10372[0].snippet or "Law" in law_10372[0].snippet

    @patch("src.components.knowledge_sources.legal_search._post_html")
    def test_filters_out_news_and_details(self, mock_post) -> None:
        """News articles and 'التفاصيل' (Details) links are excluded."""
        mock_post.return_value = _MOJ_HTML
        hits: list[SearchHit] = _search_moj_impl("قانون")
        titles: list[str] = [h.title for h in hits]
        # "التفاصيل" should not appear.
        assert "التفاصيل" not in titles
        # News article should not appear (no "قانون" or "Law" in text).
        assert "News article" not in titles

    @patch("src.components.knowledge_sources.legal_search._post_html")
    def test_empty_query_returns_empty(self, mock_post) -> None:
        hits: list[SearchHit] = _search_moj_impl("")
        assert hits == []
        mock_post.assert_not_called()

    @patch("src.components.knowledge_sources.legal_search._post_html")
    def test_network_error_returns_empty(self, mock_post) -> None:
        mock_post.return_value = ""
        hits: list[SearchHit] = _search_moj_impl("قانون")
        assert hits == []


# ---------------------------------------------------------------------------
# 3. UR Portal search
# ---------------------------------------------------------------------------


class TestSearchUrPortal:
    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_parses_json_ld(self, mock_fetch) -> None:
        """UR Portal has JSON-LD structured data with org names."""
        mock_fetch.return_value = _UR_HTML
        hits: list[SearchHit] = _search_ur_portal_impl("وزارة")
        assert len(hits) == 2
        assert "وزارة العدل" in hits[0].title
        assert hits[0].source == "UR Portal"

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_returns_notice_when_spa_empty(self, mock_fetch) -> None:
        """When the SPA has no static data, return a notice."""
        mock_fetch.return_value = _UR_EMPTY_HTML
        hits: list[SearchHit] = _search_ur_portal_impl("وزارة")
        assert len(hits) == 1
        assert "JavaScript" in hits[0].title or "SPA" in hits[0].snippet

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_empty_query_returns_empty(self, mock_fetch) -> None:
        hits: list[SearchHit] = _search_ur_portal_impl("")
        assert hits == []
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# 4. National Library search
# ---------------------------------------------------------------------------


class TestSearchNationalLibrary:
    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_parses_book_records(self, mock_fetch) -> None:
        """NLA results are <a> tags with fullrecr.php hrefs."""
        mock_fetch.return_value = _NLA_HTML
        hits: list[SearchHit] = _search_national_library_impl("محاسبة")
        assert len(hits) == 3
        # Title is the second part after splitting by "--".
        assert "title1" in hits[0].title
        assert hits[0].url.startswith("https://www.iraqnla.gov.iq/opac/fullrecr")
        assert hits[0].source == "Iraq NLA"

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_deduplicates_by_url(self, mock_fetch) -> None:
        mock_fetch.return_value = _NLA_HTML
        hits: list[SearchHit] = _search_national_library_impl("محاسبة")
        urls: list[str] = [h.url for h in hits]
        assert len(urls) == len(set(urls))  # no duplicates

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_empty_query_returns_empty(self, mock_fetch) -> None:
        hits: list[SearchHit] = _search_national_library_impl("")
        assert hits == []
        mock_fetch.assert_not_called()

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_empty_html_returns_empty(self, mock_fetch) -> None:
        mock_fetch.return_value = _EMPTY_HTML
        hits: list[SearchHit] = _search_national_library_impl("test")
        assert hits == []


# ---------------------------------------------------------------------------
# 5. MCP tool wrappers — verify they return JSON
# ---------------------------------------------------------------------------


class TestMcpToolWrappers:
    @patch("src.components.knowledge_sources.legal_search._post_html")
    def test_search_moj_tool_returns_json(self, mock_post) -> None:
        from src.components.interfaces.mcp_server import search_moj

        mock_post.return_value = _MOJ_HTML
        result: str = search_moj("قانون", max_results=5)
        parsed: list = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 2
        assert parsed[0]["source"] == "Iraq MoJ"

    @patch("src.components.knowledge_sources.legal_search._fetch_html")
    def test_search_all_tool_aggregates(self, mock_fetch) -> None:
        from src.components.interfaces.mcp_server import search_all

        def _side_effect(url: str) -> str:
            if "dijlex" in url:
                return ""  # 403 → Cloudflare notice
            if "ur.gov" in url:
                return _UR_HTML
            if "iraqnla" in url:
                return _NLA_HTML
            return ""

        mock_fetch.side_effect = _side_effect
        result: str = search_all("محاسبة", max_results=5)
        parsed: list = json.loads(result)
        sources: set[str] = {h["source"] for h in parsed}
        # NLA should have results, UR Portal should have results.
        assert "Iraq NLA" in sources


# ---------------------------------------------------------------------------
# 6. SearchHit dataclass
# ---------------------------------------------------------------------------


class TestSearchHit:
    def test_to_dict(self) -> None:
        hit: SearchHit = SearchHit(
            title="Test Law", url="https://example.com",
            snippet="A test snippet", source="Test",
        )
        d: dict = hit.to_dict()
        assert d == {
            "title": "Test Law", "url": "https://example.com",
            "snippet": "A test snippet", "source": "Test",
        }
