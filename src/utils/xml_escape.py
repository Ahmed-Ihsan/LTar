"""XML text escaping for safe insertion into OOXML documents."""

from __future__ import annotations

from xml.sax.saxutils import escape as _saxutils_escape


def escape_xml_text(text: str) -> str:
    """Escape XML special characters in *text* for safe insertion as element text.

    Wraps :func:`xml.sax.saxutils.escape` which escapes ``&``, ``<``, and ``>``.

    Args:
        text: The raw text to escape.

    Returns:
        The escaped text safe for use as XML element text content.
    """
    return _saxutils_escape(text)
