"""MCP server exposing Iraqi legal-source search tools.

Thin wrapper over :mod:`src.legal_search` — the reusable search engine.
This module only adds the MCP protocol layer (FastMCP tool registration)
so external MCP clients (Claude Desktop, Cursor, VS Code) can call the
search tools. The translation pipeline uses :mod:`src.legal_search`
directly via the ``web_search_node`` in :mod:`src.nodes`.

Run as a stdio MCP server:
    python -m src.mcp_server

Or register in your MCP client config:
    {
      "mcpServers": {
        "iraqi-legal-search": {
          "command": ".venv310\\Scripts\\python.exe",
          "args": ["-m", "src.mcp_server"]
        }
      }
    }
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from src.components.knowledge_sources.legal_search import (
    search_all_sources,
)
from src.components.knowledge_sources.legal_search import (
    search_dijlex as _search_dijlex,
)
from src.components.knowledge_sources.legal_search import (
    search_moj as _search_moj,
)
from src.components.knowledge_sources.legal_search import (
    search_national_library as _search_national_library,
)
from src.components.knowledge_sources.legal_search import (
    search_ur_portal as _search_ur_portal,
)
from src.components.translation_pipeline.exceptions import InputValidationError
from src.utils.rate_limit import TokenBucket

_MAX_QUERY_LEN: int = 500
_rate_limiter: TokenBucket = TokenBucket(rate=10.0 / 60.0, capacity=10)


def _validate_query(query: str) -> str:
    """Validate a search query; raise on empty or oversized input."""
    if not query or not query.strip():
        raise InputValidationError("query must not be empty")
    if len(query) > _MAX_QUERY_LEN:
        raise InputValidationError(
            f"query exceeds {_MAX_QUERY_LEN} characters (got {len(query)})"
        )
    return query


def _validate_max_results(n: int) -> int:
    """Clamp max_results to the allowed range [1, 100]."""
    return max(1, min(n, 100))

# ---------------------------------------------------------------------------
# MCP server — tool registration
# ---------------------------------------------------------------------------

mcp: FastMCP = FastMCP(
    "iraqi-legal-search",
    instructions=(
        "MCP server for searching Iraqi legal sources. Provides tools to "
        "search Dijlex (43k+ laws), the Iraqi Ministry of Justice, the UR "
        "e-government portal, and the Iraq National Library. Use these to "
        "look up real Iraqi laws, articles, official terminology, and entity "
        "names for the translation pipeline."
    ),
)


@mcp.tool()
def search_dijlex(query: str, max_results: int = 10) -> str:
    """Search the Dijlex Iraqi legislation database (43k+ laws, 215k+ articles).

    Use this to find Iraqi laws, articles, and legal text by keyword.
    Returns a list of results with title, URL, and snippet.

    Args:
        query: Search query (Arabic or English keywords, law name, article number).
        max_results: Maximum number of results to return (default 10).

    Returns:
        JSON string of search results.
    """
    _validate_query(query)
    n = _validate_max_results(max_results)
    if not _rate_limiter.acquire():
        return json.dumps({"error": "rate limit exceeded"}, ensure_ascii=False)
    hits = _search_dijlex(query, n)
    return json.dumps([h.to_dict() for h in hits], ensure_ascii=False, indent=2)


@mcp.tool()
def search_moj(query: str, max_results: int = 10) -> str:
    """Search the Iraqi Ministry of Justice law database.

    Contains official Iraqi laws, some with English translations.
    Use this to find the official text of Iraqi laws.

    Args:
        query: Search query (Arabic or English).
        max_results: Maximum number of results to return (default 10).

    Returns:
        JSON string of search results.
    """
    _validate_query(query)
    n = _validate_max_results(max_results)
    if not _rate_limiter.acquire():
        return json.dumps({"error": "rate limit exceeded"}, ensure_ascii=False)
    hits = _search_moj(query, n)
    return json.dumps([h.to_dict() for h in hits], ensure_ascii=False, indent=2)


@mcp.tool()
def search_ur_portal(query: str, max_results: int = 10) -> str:
    """Search the unified Iraqi e-government portal for official entity names.

    Use this to find the official names of ministries, authorities, and
    government departments — useful for terminology extraction.

    Args:
        query: Search query (Arabic or English entity name).
        max_results: Maximum number of results to return (default 10).

    Returns:
        JSON string of search results.
    """
    _validate_query(query)
    n = _validate_max_results(max_results)
    if not _rate_limiter.acquire():
        return json.dumps({"error": "rate limit exceeded"}, ensure_ascii=False)
    hits = _search_ur_portal(query, n)
    return json.dumps([h.to_dict() for h in hits], ensure_ascii=False, indent=2)


@mcp.tool()
def search_national_library(query: str, max_results: int = 10) -> str:
    """Search the Iraq National Library and Archives catalog.

    Contains legal references, books on accounting/auditing standards, and
    specialized legal literature.

    Args:
        query: Search query (Arabic or English).
        max_results: Maximum number of results to return (default 10).

    Returns:
        JSON string of search results.
    """
    _validate_query(query)
    n = _validate_max_results(max_results)
    if not _rate_limiter.acquire():
        return json.dumps({"error": "rate limit exceeded"}, ensure_ascii=False)
    hits = _search_national_library(query, n)
    return json.dumps([h.to_dict() for h in hits], ensure_ascii=False, indent=2)


@mcp.tool()
def search_all(query: str, max_results: int = 5) -> str:
    """Search ALL Iraqi legal sources at once (Dijlex, MoJ, UR Portal, NLA).

    Aggregates results from all four sources. Use this for broad searches
    when you don't know which source has the answer.

    Args:
        query: Search query (Arabic or English).
        max_results: Max results per source (default 5, so up to 20 total).

    Returns:
        JSON string of aggregated search results.
    """
    _validate_query(query)
    n = _validate_max_results(max_results)
    if not _rate_limiter.acquire():
        return json.dumps({"error": "rate limit exceeded"}, ensure_ascii=False)
    hits = search_all_sources(query, max_results_per_source=n)
    return json.dumps(
        [h.to_dict() for h in hits], ensure_ascii=False, indent=2
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP server on stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
