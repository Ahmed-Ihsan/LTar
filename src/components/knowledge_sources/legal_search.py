"""Iraqi legal-source web search — reusable search functions.

Single responsibility: search Iraqi legal databases and portals for laws,
articles, terminology, and official entity names. Returns structured
:class:`SearchHit` results. No MCP dependency — this module is the pure
search engine that both the MCP server (``src/mcp_server.py``) and the
translation pipeline (``src/nodes.py`` web_search_node) use.

Sources:
1. Dijlex — 43k+ laws, 215k+ articles (Cloudflare-protected, may 403).
2. Ministry of Justice (MoJ) — official Iraqi laws, some EN translations.
3. UR Portal — government entity names (Vue.js SPA, limited static data).
4. National Library (NLA) — legal books and references.

All functions are read-only (HTTP GET/POST, no side effects). Network
errors return empty lists — never raise (the pipeline must not crash on
a web search failure).
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx
from bs4 import BeautifulSoup

from src.components.knowledge_sources.models import SearchHit
from src.components.translation_pipeline.exceptions import LegalSearchBlockedError

logger = logging.getLogger(__name__)

_SEARCH_CACHE_TTL: float = 300.0  # 5 minutes
_search_cache: dict[tuple[str, int], tuple[float, list[SearchHit]]] = {}


def _cached_search(
    fn: Callable[[str, int], list[SearchHit]],
) -> Callable[[str, int], list[SearchHit]]:
    """Decorator: cache search results for 5 minutes (PERF-11)."""

    def wrapper(query: str, max_results: int = 10) -> list[SearchHit]:
        key: tuple[str, int] = (query, max_results)
        now: float = time.monotonic()
        cached: tuple[float, list[SearchHit]] | None = _search_cache.get(key)
        if cached is not None and (now - cached[0]) < _SEARCH_CACHE_TTL:
            return list(cached[1])
        result: list[SearchHit] = fn(query, max_results)
        _search_cache[key] = (now, list(result))
        return result

    return wrapper

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_TIMEOUT: float = 15.0  # seconds per HTTP request
_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_HEADERS: dict[str, str] = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Security: allowed-host allowlist (harden-untrusted-input-surfaces §7)
# ---------------------------------------------------------------------------

_ALLOWED_HOSTS: frozenset[str] = frozenset({
    "moj.gov.iq",
    "www.moj.gov.iq",
    "dijlex.com",
    "www.dijlex.com",
    "urportal.ur.gov.iq",
    "www.urportal.ur.gov.iq",
    "nlb.gov.iq",
    "www.nlb.gov.iq",
})

_MAX_REDIRECT_HOPS: int = 3
_MAX_JSONLD_BYTES: int = 1_048_576  # 1 MiB cap on JSON-LD script content


def _validate_url(url: str) -> str:
    """Validate that *url* points to an allowed host; raise on mismatch."""
    parsed = urlparse(url)
    host: str | None = parsed.hostname
    if host is None or host not in _ALLOWED_HOSTS:
        raise LegalSearchBlockedError(
            f"URL host '{host}' is not on the allowed list"
        )
    return url

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class SearchSource:
    """A registered legal search source (OCP).

    Add new sources by appending to ``_SOURCES`` — no edits to
    ``search_all_sources`` required.
    """

    name: str
    search: Callable[[str, int], list[SearchHit]]


# ---------------------------------------------------------------------------
# HTTP fetch + parse helpers
# ---------------------------------------------------------------------------


def _fetch_html(url: str) -> str:
    """Fetch HTML content from ``url`` with a timeout. Returns empty on error.

    Redirects are manually validated against the allowed-host allowlist
    (harden-untrusted-input-surfaces §7.3) — auto-follow is disabled.
    """
    try:
        _validate_url(url)
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
            resp: httpx.Response = client.get(url, headers=_HEADERS)
            for _ in range(_MAX_REDIRECT_HOPS):
                if resp.is_redirect:
                    loc: str = resp.headers.get("location", "")
                    if not loc:
                        break
                    # Resolve relative redirects against the original URL.
                    next_url: str = str(httpx.URL(url).join(loc))
                    _validate_url(next_url)
                    resp = client.get(next_url, headers=_HEADERS)
                else:
                    break
            resp.raise_for_status()
            return resp.text
    except (httpx.HTTPError, ValueError, LegalSearchBlockedError) as e:
        logger.warning("legal_search fetch failed: %s", e)
        return ""


def _post_html(url: str, data: dict[str, str]) -> str:
    """POST form data and return HTML. Returns empty on error.

    Redirects are manually validated against the allowed-host allowlist
    (harden-untrusted-input-surfaces §7.3) — auto-follow is disabled.
    """
    try:
        _validate_url(url)
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
            resp: httpx.Response = client.post(
                url, data=data, headers={
                    **_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            for _ in range(_MAX_REDIRECT_HOPS):
                if resp.is_redirect:
                    loc: str = resp.headers.get("location", "")
                    if not loc:
                        break
                    next_url: str = str(httpx.URL(url).join(loc))
                    _validate_url(next_url)
                    resp = client.get(next_url, headers=_HEADERS)
                else:
                    break
            resp.raise_for_status()
            return resp.text
    except (httpx.HTTPError, ValueError, LegalSearchBlockedError) as e:
        logger.warning("legal_search POST failed: %s", e)
        return ""


def _clean_text(text: str) -> str:
    """Collapse whitespace and strip noise from a snippet."""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# 1. Dijlex — Iraqi legislation database
# ---------------------------------------------------------------------------

_DIJLEX_SEARCH_URL: str = "https://dijlex.com/search"


@_cached_search
def search_dijlex(query: str, max_results: int = 10) -> list[SearchHit]:
    """Search Dijlex for Iraqi laws and articles.

    Dijlex hosts 43k+ laws and 215k+ articles. Behind Cloudflare — may
    return 403 to automated requests, in which case a notice hit is returned.
    """
    if not query.strip():
        return []
    params: str = urlencode({"q": query, "type": "all"})
    url: str = f"{_DIJLEX_SEARCH_URL}?{params}"
    html: str = _fetch_html(url)
    if not html:
        return [SearchHit(
            title="Dijlex search blocked (403 Cloudflare)",
            url=url,
            snippet=(
                "Dijlex is protected by Cloudflare and blocks automated "
                "requests. Try searching manually at https://dijlex.com"
            ),
            source="Dijlex",
        )]
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    hits: list[SearchHit] = []

    for card in soup.select(".search-result, .law-card, .result-item, article"):
        title_el = card.select_one("h2, h3, .title, a")
        link_el = card.select_one("a[href]")
        snippet_el = card.select_one(".snippet, .description, p")
        if not title_el or not link_el:
            continue
        title: str = _clean_text(title_el.get_text())
        href: str = str(link_el.get("href", ""))
        if href and not href.startswith("http"):
            href = f"https://dijlex.com{href}"
        snippet: str = _clean_text(snippet_el.get_text()) if snippet_el else ""
        if title:
            hits.append(SearchHit(
                title=title, url=href, snippet=snippet, source="Dijlex",
            ))
        if len(hits) >= max_results:
            break

    if not hits:
        for a in soup.find_all("a", href=True):
            text: str = _clean_text(a.get_text())
            if text and len(text) > 5 and ("law" in text.lower()
                                           or "قانون" in text
                                           or "مادة" in text):
                href = str(a["href"])
                if href and not href.startswith("http"):
                    href = f"https://dijlex.com{href}"
                hits.append(SearchHit(
                    title=text, url=href, snippet="", source="Dijlex",
                ))
                if len(hits) >= max_results:
                    break

    return hits[:max_results]


# ---------------------------------------------------------------------------
# 2. Ministry of Justice — official Iraqi laws
# ---------------------------------------------------------------------------

_MOJ_SEARCH_URL: str = "https://moj.gov.iq/search.php"


@_cached_search
def search_moj(query: str, max_results: int = 10) -> list[SearchHit]:
    """Search the Iraqi Ministry of Justice law database.

    Uses POST with a ``words`` field. Filters for law-related links
    (href containing ``/view.`` and text containing ``قانون`` or ``Law``).
    Deduplicates AR+EN titles by URL.
    """
    if not query.strip():
        return []
    html: str = _post_html(_MOJ_SEARCH_URL, {"words": query})
    if not html:
        return []
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    hits_by_url: dict[str, SearchHit] = {}

    for a in soup.find_all("a", href=True):
        href: str = str(a["href"])
        text: str = _clean_text(a.get_text())
        if not href or not text or len(text) < 5:
            continue
        if "/view." not in href:
            continue
        if text in ("التفاصيل", "Details"):
            continue
        is_law: bool = (
            "قانون" in text
            or "Law" in text
            or "law" in text.lower()
            or "No." in text
            or "رقم" in text
        )
        if not is_law:
            continue
        full_url: str = href
        if not full_url.startswith("http"):
            full_url = f"https://moj.gov.iq{href}"
        if full_url in hits_by_url:
            existing: SearchHit = hits_by_url[full_url]
            if text not in existing.snippet:
                new_snippet: str = (
                    f"{existing.snippet} | {text}" if existing.snippet else text
                )
                hits_by_url[full_url] = SearchHit(
                    title=existing.title, url=existing.url,
                    snippet=new_snippet, source=existing.source,
                )
            continue
        hits_by_url[full_url] = SearchHit(
            title=text, url=full_url, snippet="", source="Iraq MoJ",
        )
        if len(hits_by_url) >= max_results:
            break

    return list(hits_by_url.values())[:max_results]


# ---------------------------------------------------------------------------
# 3. UR Portal — government entities and official names
# ---------------------------------------------------------------------------

_UR_SEARCH_URL: str = "https://ur.gov.iq/index/all-orgs/"


@_cached_search
def search_ur_portal(query: str, max_results: int = 10) -> list[SearchHit]:
    """Search the unified e-government portal for ministry/authority names.

    Vue.js SPA — tries JSON-LD structured data first, then static links.
    Returns a notice hit if no data is found (SPA limitation).
    """
    if not query.strip():
        return []
    html: str = _fetch_html(_UR_SEARCH_URL)
    if not html:
        return []
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    hits: list[SearchHit] = []
    query_lower: str = query.lower()

    # Strategy 1: JSON-LD structured data.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json

            raw: str = script.string or ""
            # Skip oversized JSON-LD blocks (harden-untrusted-input-surfaces §7.4).
            if len(raw) > _MAX_JSONLD_BYTES:
                continue
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                if not isinstance(item, dict):
                    continue
                name: str = item.get("name", "")
                url: str = item.get("url", "")
                org_type: str = item.get("@type", "")
                if name and query_lower in name.lower():
                    hits.append(SearchHit(
                        title=name, url=url or _UR_SEARCH_URL,
                        snippet=f"Type: {org_type}", source="UR Portal",
                    ))
                    if len(hits) >= max_results:
                        return hits[:max_results]
        except (json.JSONDecodeError, TypeError):
            continue

    # Strategy 2: scan all links.
    for a in soup.find_all("a", href=True):
        text: str = _clean_text(a.get_text())
        if not text or len(text) < 3:
            continue
        if query_lower in text.lower() or query in text:
            href: str = str(a["href"])
            if href and not href.startswith("http"):
                href = f"https://ur.gov.iq{href}"
            hits.append(SearchHit(
                title=text, url=href, snippet="", source="UR Portal",
            ))
            if len(hits) >= max_results:
                break

    if not hits:
        hits.append(SearchHit(
            title="UR Portal requires JavaScript rendering",
            url=_UR_SEARCH_URL,
            snippet=(
                "The UR Portal is a Vue.js SPA that loads ministry data "
                "dynamically. Static HTML scraping cannot retrieve the org "
                "list. Visit the URL manually to browse ministries."
            ),
            source="UR Portal",
        ))

    return hits[:max_results]


# ---------------------------------------------------------------------------
# 4. National Library — legal references and books
# ---------------------------------------------------------------------------

_NLA_SEARCH_URL: str = "https://www.iraqnla.gov.iq/opac/index.php"


@_cached_search
def search_national_library(query: str, max_results: int = 10) -> list[SearchHit]:
    """Search the Iraq National Library and Archives catalog.

    Results are ``<a>`` tags with ``fullrecr.php`` in href. Text format is
    ``author--title--year--type`` (separated by double dashes).
    """
    if not query.strip():
        return []
    params: str = urlencode({"hl": "ara", "q": query})
    url: str = f"{_NLA_SEARCH_URL}?{params}"
    html: str = _fetch_html(url)
    if not html:
        return []
    soup: BeautifulSoup = BeautifulSoup(html, "html.parser")
    hits: list[SearchHit] = []
    seen_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        href: str = str(a["href"])
        if "fullrecr" not in href:
            continue
        text: str = _clean_text(a.get_text())
        if not text or len(text) < 3:
            continue
        full_url: str = href
        if not full_url.startswith("http"):
            full_url = f"https://www.iraqnla.gov.iq/opac/{href}"
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        parts: list[str] = [p.strip() for p in text.split("--")]
        title: str = parts[1] if len(parts) > 1 else text
        snippet: str = " | ".join(parts) if len(parts) > 1 else ""
        hits.append(SearchHit(
            title=title, url=full_url, snippet=snippet, source="Iraq NLA",
        ))
        if len(hits) >= max_results:
            break

    return hits[:max_results]


# ---------------------------------------------------------------------------
# 5. Aggregated search — all sources at once
# ---------------------------------------------------------------------------

_SOURCES: list[SearchSource] = [
    SearchSource(name="Dijlex", search=search_dijlex),
    SearchSource(name="Iraq MoJ", search=search_moj),
    SearchSource(name="UR Portal", search=search_ur_portal),
    SearchSource(name="Iraq NLA", search=search_national_library),
]


def search_all_sources(
    query: str, max_results_per_source: int = 5,
) -> list[SearchHit]:
    """Search ALL Iraqi legal sources and aggregate results.

    Iterates over the ``_SOURCES`` registry (OCP — adding a new source only
    requires appending a :class:`SearchSource` entry, no function edits).
    """
    all_hits: list[SearchHit] = []
    for source in _SOURCES:
        all_hits.extend(source.search(query, max_results_per_source))
    return all_hits
