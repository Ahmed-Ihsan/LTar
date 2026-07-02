"""Unit tests for glossary validation (DATA_SPEC §2.5, task 2.1.4).

Invalid files are rejected with a clear error listing the offending field.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.exceptions import GlossaryConflictError, GlossaryValidationError
from src.glossary import load_glossary_file

pytestmark = pytest.mark.unit


def _write_glossary(tmp_path: Path, payload: object, name: str = "bad.json") -> Path:
    path: Path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _valid_term(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source_term": "عقد البيع",
        "source_lang": "ar",
        "target_term": "contract of sale",
        "target_lang": "en",
        "law_ref": "Civil Code",
    }
    base.update(overrides)
    return base


def _valid_file(terms: list[dict[str, object]]) -> dict[str, object]:
    return {
        "domain": "civil_code",
        "version": "1.0.0",
        "last_updated": "2026-07-01",
        "terms": terms,
    }


class TestValidationRejection:
    def test_missing_required_file_field(self, tmp_path: Path) -> None:
        path = _write_glossary(
            tmp_path,
            {"version": "1.0.0", "last_updated": "2026-07-01", "terms": [_valid_term()]},
        )
        with pytest.raises(GlossaryValidationError, match="domain"):
            load_glossary_file(path)

    def test_missing_required_term_field(self, tmp_path: Path) -> None:
        term = _valid_term()
        del term["law_ref"]
        path = _write_glossary(tmp_path, _valid_file([term]))
        with pytest.raises(GlossaryValidationError, match="law_ref"):
            load_glossary_file(path)

    def test_same_source_and_target_lang_rejected(self, tmp_path: Path) -> None:
        term = _valid_term(source_lang="ar", target_lang="ar", target_term="عقد")
        path = _write_glossary(tmp_path, _valid_file([term]))
        with pytest.raises(GlossaryValidationError, match="no-op entry"):
            load_glossary_file(path)

    def test_empty_source_term_rejected(self, tmp_path: Path) -> None:
        term = _valid_term(source_term="   ")
        path = _write_glossary(tmp_path, _valid_file([term]))
        with pytest.raises(GlossaryValidationError, match="source_term"):
            load_glossary_file(path)

    def test_empty_terms_array_rejected(self, tmp_path: Path) -> None:
        path = _write_glossary(tmp_path, _valid_file([]))
        with pytest.raises(GlossaryValidationError, match="non-empty"):
            load_glossary_file(path)

    def test_malformed_json_rejected(self, tmp_path: Path) -> None:
        path: Path = tmp_path / "broken.json"
        path.write_text("{ not valid json ", encoding="utf-8")
        with pytest.raises(GlossaryValidationError, match="invalid JSON"):
            load_glossary_file(path)

    def test_error_lists_offending_field_and_file(
        self, tmp_path: Path
    ) -> None:
        term = _valid_term()
        del term["target_term"]
        path = _write_glossary(tmp_path, _valid_file([term]), name="offending.json")
        with pytest.raises(GlossaryValidationError) as exc_info:
            load_glossary_file(path)
        message: str = str(exc_info.value)
        assert "offending.json" in message
        assert "target_term" in message


class TestDuplicateDetection:
    def test_intra_file_duplicate_rejected(self, tmp_path: Path) -> None:
        t1 = _valid_term(source_term="عقد البيع", target_term="contract of sale")
        t2 = _valid_term(source_term="عقد البيع", target_term="sale contract")
        path = _write_glossary(tmp_path, _valid_file([t1, t2]))
        with pytest.raises(GlossaryConflictError, match="duplicate term"):
            load_glossary_file(path)
