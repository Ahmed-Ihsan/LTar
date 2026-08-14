"""Tests for the UN international glossary file (MultiUN-extracted terms)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.components.knowledge_sources.glossary import load_glossary_file, load_glossary_files

pytestmark = pytest.mark.unit

_GLOSSARY_DIR: Path = Path(__file__).resolve().parent.parent.parent / "data" / "glossary"
_UN_FILE: Path = _GLOSSARY_DIR / "un_international.json"


def test_un_international_file_exists():
    """The converted glossary file must exist."""
    assert _UN_FILE.exists(), (
        f"{_UN_FILE} not found. Run data/external/convert_terms.py first."
    )


def test_un_international_loads_valid_terms():
    """The file must pass glossary validation and load as Term objects."""
    terms = load_glossary_file(_UN_FILE)
    assert len(terms) > 0
    for term in terms:
        assert term.source_lang in ("ar", "en")
        assert term.target_lang in ("ar", "en")
        assert term.source_lang != term.target_lang
        assert term.law_ref  # must have the required law_ref field
        assert term.domain == "un_international"


def test_un_international_priority_is_lower_than_iq_glossary():
    """UN terms should have priority ≤ 5 (lower than Iraqi-law glossary 9-10)."""
    terms = load_glossary_file(_UN_FILE)
    for term in terms:
        assert term.priority <= 5, (
            f"Term '{term.source_term}' has priority {term.priority} > 5; "
            "UN-extracted terms must be lower priority than Iraqi-law terms."
        )


def test_all_glossary_files_load_together():
    """All glossary files (including UN) must load without cross-file conflicts."""
    terms = load_glossary_files(_GLOSSARY_DIR / "*.json")
    assert len(terms) > 50  # 15+8+10 Iraqi + 59 UN = 92
    # Verify UN terms are present.
    un_terms = [t for t in terms if t.domain == "un_international"]
    assert len(un_terms) > 0
