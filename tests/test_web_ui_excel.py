"""Tests for the Excel tab in the pywebview desktop UI (``web_ui.Api``).

Coverage (per openspec/changes/add-excel-ui §10):
- ``Api.translate_excel`` starts a job and ``get_excel_status`` reports
  progress then a final report.
- Cancellation: ``cancel_excel`` stops the run and the final report has
  ``cancelled=True``.
- Concurrent-job guard: a second ``translate_excel`` call while one is
  running returns an error state.
- Invalid input (missing file) returns an error state without starting a job.
- Options override: passing ``translate_comments=False`` is respected (the
  report's segment count differs from the default run).
- Thread safety: the JS-bridge methods do not block the UI thread (the
  background thread is used; ``translate_excel`` returns before the run
  completes).

Uses the deterministic ``mock_llm`` / ``mock_embedder`` / in-memory
``GlossaryIndex`` / temp ChromaDB from ``tests/conftest.py`` and a
programmatically-built ``.xlsx`` fixture (reuses ``test_excel.py``'s builder
pattern). Never hits the real Ollama daemon.
"""
from __future__ import annotations

import threading
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from src.components.interfaces.models import Adapters
from src.components.interfaces.web_ui import Api
from src.config import AppConfig

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Minimal .xlsx builder (raw OOXML — reuses test_excel.py's pattern)
# ---------------------------------------------------------------------------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/><Override PartName="/xl/comments1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/></Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"""

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments1.xml"/></Relationships>"""

_SHARED = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3"><si><t>عقد البيع</t></si><si><t>المادة 148</t></si><si><t>تقرير</t></si></sst>"""

_SHEET1 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetData><c r="A1" t="s"><v>0</v></c><c r="A2" t="s"><v>1</v></c><c r="A3" t="s"><v>2</v></c></sheetData></worksheet>"""

_COMMENTS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><authors><author>legal</author></authors><commentList><comment ref="A1" authorId="0"><text><t>ملاحظة قانونية</t></text></comment></commentList></comments>"""


def _build_workbook() -> bytes:
    """Assemble a minimal .xlsx with shared strings + comments."""
    parts: dict[str, bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "xl/workbook.xml": _WORKBOOK,
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/sharedStrings.xml": _SHARED,
        "xl/worksheets/sheet1.xml": _SHEET1,
        "xl/comments1.xml": _COMMENTS,
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data.encode("utf-8"))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helpers
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


def _default_options(config: AppConfig) -> dict[str, Any]:
    return {
        "translate_comments": config.excel.translate_comments,
        "translate_headers_footers": config.excel.translate_headers_footers,
        "translate_chart_titles": config.excel.translate_chart_titles,
        "max_segment_chars": config.excel.max_segment_chars,
    }


def _wait_for_completion(api: Api, job_id: str, timeout: float = 30.0) -> dict[str, Any]:
    """Poll ``get_excel_status`` until the job leaves the running state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = api.get_excel_status(job_id)
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not complete within {timeout}s")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebUiExcel:
    def test_translate_excel_starts_job_and_reports_report(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        res = api.translate_excel(api.get_token(), str(in_path), str(out_path), "ar-en", _default_options(config),
        )
        assert res["state"] == "running"
        job_id: str = res["job_id"]
        assert isinstance(job_id, str) and job_id

        status = _wait_for_completion(api, job_id)
        assert status["state"] == "done"
        report = status["report"]
        assert report is not None
        assert report["total_segments"] > 0
        assert report["translated"] == report["total_segments"]
        assert report["failed"] == 0
        assert report["cancelled"] is False
        assert out_path.is_file()

    def test_cancel_excel_stops_run_and_report_cancelled(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        res = api.translate_excel(api.get_token(), str(in_path), str(out_path), "ar-en", _default_options(config),
        )
        job_id: str = res["job_id"]
        api.cancel_excel(job_id)

        status = _wait_for_completion(api, job_id)
        assert status["state"] == "cancelled"
        report = status["report"]
        assert report is not None
        assert report["cancelled"] is True
        # Output file still written with already-translated segments patched.
        assert out_path.is_file()

    def test_second_translate_excel_rejected_while_running(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        first = api.translate_excel(api.get_token(), str(in_path), str(out_path), "ar-en", _default_options(config),
        )
        assert first["state"] == "running"
        # Immediately start a second job — must be rejected.
        second = api.translate_excel(api.get_token(), str(in_path), str(out_path), "ar-en", _default_options(config),
        )
        assert second["state"] == "error"
        assert "already in progress" in second["error"].lower()
        # Wait for the first to finish so the background thread exits cleanly.
        _wait_for_completion(api, first["job_id"])

    def test_missing_input_returns_error_without_starting(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        res = api.translate_excel(
            api.get_token(),
            str(tmp_path / "missing.xlsx"),
            str(tmp_path / "out.xlsx"),
            "ar-en", _default_options(config),
        )
        assert res["state"] == "error"
        assert "not found" in res["error"].lower()
        # No job slot was created.
        assert api.is_busy() is False

    def test_options_override_translate_comments_false(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        # Default run (comments enabled) — includes the comment text.
        default_opts = _default_options(config)
        res1 = api.translate_excel(api.get_token(), str(in_path), str(out_path), "ar-en", default_opts,
        )
        s1 = _wait_for_completion(api, res1["job_id"])
        total_with_comments: int = s1["report"]["total_segments"]

        # Override run (comments disabled) — should have fewer segments
        # because the comment text "ملاحظة قانونية" is no longer extracted.
        opts_off = dict(default_opts)
        opts_off["translate_comments"] = False
        res2 = api.translate_excel(api.get_token(), str(in_path), str(out_path), "ar-en", opts_off,
        )
        s2 = _wait_for_completion(api, res2["job_id"])
        total_without_comments: int = s2["report"]["total_segments"]

        assert total_without_comments < total_with_comments
        # The global config is unchanged (in-memory override only).
        assert config.excel.translate_comments is True

    def test_translate_excel_returns_before_run_completes(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        """Thread safety: translate_excel returns immediately; the run runs
        in a background thread, so the calling (UI) thread is not blocked."""
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        # Block the mock LLM so the run takes a measurable amount of time.
        gate = threading.Event()

        def _gated_generate(system, user, **kw):
            gate.wait(timeout=5.0)
            return original_generate(system, user, **kw)

        original_generate = mock_llm.generate
        mock_llm.generate = _gated_generate  # type: ignore[method-assign]
        try:
            start = time.time()
            res = api.translate_excel(api.get_token(), str(in_path), str(out_path), "ar-en", _default_options(config),
            )
            elapsed = time.time() - start
            # The call returned immediately (well under a second), proving
            # the UI thread was not blocked.
            assert elapsed < 1.0
            assert res["state"] == "running"
            assert api.is_busy() is True
        finally:
            # Release the gate so the background thread can finish.
            gate.set()
            _wait_for_completion(api, res["job_id"])
            mock_llm.generate = original_generate  # type: ignore[method-assign]

    def test_get_excel_options_returns_cfg_excel_values(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        opts = api.get_excel_options()
        assert opts["translate_comments"] == config.excel.translate_comments
        assert opts["translate_headers_footers"] == config.excel.translate_headers_footers
        assert opts["translate_chart_titles"] == config.excel.translate_chart_titles
        assert opts["max_segment_chars"] == config.excel.max_segment_chars

    def test_wrong_extension_returns_error(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        adapters = _make_adapters(mock_llm, mock_embedder, glossary_index, persist_dir)
        api = Api(config, adapters)

        bad = tmp_path / "data.csv"
        bad.write_text("a,b\n1,2\n", encoding="utf-8")
        res = api.translate_excel(
            api.get_token(),
            str(bad), str(tmp_path / "out.xlsx"), "ar-en", _default_options(config),
        )
        assert res["state"] == "error"
        assert ".xlsx" in res["error"].lower()
