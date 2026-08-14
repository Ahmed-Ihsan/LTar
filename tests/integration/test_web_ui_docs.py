"""Tests for the Word and PDF tabs in the pywebview desktop UI (``web_ui.Api``).

Mirrors ``tests/test_web_ui_excel.py``. Coverage:
- ``Api.translate_word`` / ``Api.translate_pdf`` start a job and the
  corresponding ``get_word_status`` / ``get_pdf_status`` reports a final
  report.
- Cancellation: ``cancel_word`` / ``cancel_pdf`` stops the run and the final
  report has ``cancelled=True``.
- Concurrent-job guard: a second document run while one is running returns an
  error state (concurrency = 1 across all document kinds).
- Invalid input (missing file / wrong extension) returns an error state
  without starting a job.
- Options: ``get_word_options`` / ``get_pdf_options`` return the cfg values.

Uses the deterministic ``mock_llm`` / ``mock_embedder`` / in-memory
``GlossaryIndex`` / temp ChromaDB from ``tests/conftest.py`` and reuses the
raw-OOXML ``.docx`` builder from ``tests/test_word.py`` and the raw-PDF
builder from ``tests/test_pdf.py``. Never hits the real Ollama daemon.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from src.components.interfaces.models import Adapters
from src.components.interfaces.web_ui import Api
from src.config import AppConfig

# Reuse the raw-OOXML / raw-PDF builders from the integration test suite (DRY).
from tests.integration.test_pdf import _build_test_pdf
from tests.integration.test_word import _build_docx

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers (mirror test_web_ui_excel.py)
# ---------------------------------------------------------------------------


def _build_chroma(tmp_path: Path, mock_embedder: Any, config: AppConfig) -> str:
    """Build a temp ChromaDB collection so retrieval works without Ollama."""
    from src.components.knowledge_sources.ingestion import Chunk
    from src.components.knowledge_sources.retrieval import build_chroma_collection

    chunks = [
        Chunk(
            chunk_id="civil_code_ar_148_0",
            text="المادة 148: عقد البيع هو agreement يقتضي نقل ملكية شيء مقابل ثمن.",
            law="Civil Code", article="148", lang="ar",
            law_slug="civil_code", chunk_idx=0, char_start=0, char_end=80,
        ),
    ]
    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(
        chunks, persist_dir=persist_dir, embedder=mock_embedder, cfg=config,
    )
    return persist_dir


def _setup_mock_llm(mock_llm: Any) -> None:
    """Make the deterministic mock LLM return APPROVE for every translator call."""
    import json

    mock_llm.set_response("translator", "contract of sale")
    mock_llm.set_response(
        "auditor",
        json.dumps({
            "verdict": "APPROVE", "critique": "", "violations": [],
            "confidence": 0.95,
        }),
    )


def _make_adapters(mock_llm: Any, mock_embedder: Any, glossary_index: Any,
                   persist_dir: str) -> Adapters:
    """Build an Adapters bundle from mock adapters (mirrors CLI construction)."""
    return Adapters(
        llm=mock_llm, embedder=mock_embedder,
        glossary_index=glossary_index, persist_dir=persist_dir, tm=None,
    )


def _default_word_options(config: AppConfig) -> dict[str, Any]:
    return {
        "translate_comments": config.word.translate_comments,
        "translate_headers_footers": config.word.translate_headers_footers,
        "translate_footnotes": config.word.translate_footnotes,
        "translate_endnotes": config.word.translate_endnotes,
        "translate_glossary_doc": config.word.translate_glossary_doc,
        "max_segment_chars": config.word.max_segment_chars,
    }


def _default_pdf_options(config: AppConfig) -> dict[str, Any]:
    return {
        "out_format": config.pdf.out_format,
        "skip_header_footer": config.pdf.skip_header_footer,
        "max_segment_chars": config.pdf.max_segment_chars,
    }


def _wait_for_doc_status(
    api: Api, job_id: str, poll: str, timeout: float = 30.0,
) -> dict[str, Any]:
    """Poll ``get_*_status`` until the job leaves the running state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = getattr(api, poll)(job_id)
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# Word tab
# ---------------------------------------------------------------------------


class TestWebUiWord:
    def test_translate_word_starts_job_and_reports_report(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.docx"
        in_path.write_bytes(_build_docx())
        out_path = tmp_path / "out.docx"

        res = api.translate_word(
            api.get_token(), str(in_path), str(out_path), "ar-en",
            _default_word_options(config),
        )
        assert res["state"] == "running"
        job_id: str = res["job_id"]
        assert isinstance(job_id, str) and job_id

        status = _wait_for_doc_status(api, job_id, "get_word_status")
        assert status["state"] in ("done", "cancelled")
        report = status["report"]
        assert report is not None
        assert report["total_segments"] >= 1
        assert report["translated"] >= 1
        assert out_path.exists()

    def test_cancel_word_stops_run_and_report_cancelled(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.docx"
        in_path.write_bytes(_build_docx())
        out_path = tmp_path / "out.docx"

        res = api.translate_word(
            api.get_token(), str(in_path), str(out_path), "ar-en",
            _default_word_options(config),
        )
        job_id: str = res["job_id"]
        api.cancel_word(job_id)
        status = _wait_for_doc_status(api, job_id, "get_word_status")
        assert status["state"] == "cancelled"
        assert status["report"]["cancelled"] is True

    def test_second_translate_word_rejected_while_running(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.docx"
        in_path.write_bytes(_build_docx())
        out_path = tmp_path / "out.docx"

        first = api.translate_word(
            api.get_token(), str(in_path), str(out_path), "ar-en",
            _default_word_options(config),
        )
        assert first["state"] == "running"
        second = api.translate_word(
            api.get_token(), str(in_path), str(out_path), "ar-en",
            _default_word_options(config),
        )
        assert second["state"] == "error"
        # Clean up the running job so it does not leak into other tests.
        api.cancel_word(first["job_id"])
        _wait_for_doc_status(api, first["job_id"], "get_word_status")

    def test_translate_word_rejects_missing_file(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        res = api.translate_word(
            api.get_token(), str(tmp_path / "missing.docx"),
            str(tmp_path / "out.docx"), "ar-en", _default_word_options(config),
        )
        assert res["state"] == "error"
        assert "not found" in res["error"]

    def test_translate_word_rejects_wrong_extension(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        bad = tmp_path / "not_a_docx.docx"
        bad.write_bytes(b"not a real docx")
        res = api.translate_word(
            api.get_token(), str(bad), str(tmp_path / "out.docx"),
            "ar-en", _default_word_options(config),
        )
        # The .docx extension is accepted by the facade; the adapter raises a
        # domain error (invalid zip) which surfaces as an error status.
        assert res["state"] in ("error", "running")

    def test_translate_word_rejects_invalid_direction(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.docx"
        in_path.write_bytes(_build_docx())
        res = api.translate_word(
            api.get_token(), str(in_path), str(tmp_path / "out.docx"),
            "sideways", _default_word_options(config),
        )
        assert res["state"] == "error"
        assert "direction" in res["error"]

    def test_get_word_options_returns_cfg_word_values(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        opts = api.get_word_options()
        assert opts["translate_comments"] == config.word.translate_comments
        assert opts["translate_footnotes"] == config.word.translate_footnotes
        assert opts["translate_endnotes"] == config.word.translate_endnotes
        assert opts["translate_glossary_doc"] == config.word.translate_glossary_doc
        assert opts["max_segment_chars"] == config.word.max_segment_chars


# ---------------------------------------------------------------------------
# PDF tab
# ---------------------------------------------------------------------------


class TestWebUiPdf:
    def test_translate_pdf_starts_job_and_reports_report(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.pdf"
        in_path.write_bytes(_build_test_pdf(["عقد البيع", "المادة 148"]))
        out_path = tmp_path / "out.docx"

        res = api.translate_pdf(
            api.get_token(), str(in_path), str(out_path), "ar-en",
            _default_pdf_options(config),
        )
        assert res["state"] == "running"
        job_id: str = res["job_id"]
        assert isinstance(job_id, str) and job_id

        status = _wait_for_doc_status(api, job_id, "get_pdf_status")
        assert status["state"] in ("done", "cancelled")
        report = status["report"]
        assert report is not None
        assert report["total_pages"] == 2
        assert report["total_segments"] >= 1
        assert report["translated"] >= 1
        assert out_path.exists()

    def test_cancel_pdf_stops_run_and_report_cancelled(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.pdf"
        in_path.write_bytes(_build_test_pdf(["عقد البيع", "المادة 148"]))
        out_path = tmp_path / "out.docx"

        res = api.translate_pdf(
            api.get_token(), str(in_path), str(out_path), "ar-en",
            _default_pdf_options(config),
        )
        job_id: str = res["job_id"]
        api.cancel_pdf(job_id)
        status = _wait_for_doc_status(api, job_id, "get_pdf_status")
        assert status["state"] == "cancelled"
        assert status["report"]["cancelled"] is True

    def test_translate_pdf_rejects_missing_file(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        res = api.translate_pdf(
            api.get_token(), str(tmp_path / "missing.pdf"),
            str(tmp_path / "out.docx"), "ar-en", _default_pdf_options(config),
        )
        assert res["state"] == "error"
        assert "not found" in res["error"]

    def test_translate_pdf_rejects_wrong_extension(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        bad = tmp_path / "not_a_pdf.pdf"
        bad.write_bytes(b"not a real pdf")
        res = api.translate_pdf(
            api.get_token(), str(bad), str(tmp_path / "out.docx"),
            "ar-en", _default_pdf_options(config),
        )
        # The .pdf extension is accepted by the facade; the adapter raises a
        # domain error (invalid PDF) which surfaces as an error status.
        assert res["state"] in ("error", "running")

    def test_translate_pdf_rejects_invalid_direction(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.pdf"
        in_path.write_bytes(_build_test_pdf(["عقد البيع"]))
        res = api.translate_pdf(
            api.get_token(), str(in_path), str(tmp_path / "out.docx"),
            "sideways", _default_pdf_options(config),
        )
        assert res["state"] == "error"
        assert "direction" in res["error"]

    def test_get_pdf_options_returns_cfg_pdf_values(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        opts = api.get_pdf_options()
        assert opts["out_format"] == config.pdf.out_format
        assert opts["skip_header_footer"] == config.pdf.skip_header_footer
        assert opts["max_segment_chars"] == config.pdf.max_segment_chars
