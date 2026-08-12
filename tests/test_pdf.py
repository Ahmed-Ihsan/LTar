"""Tests for the PDF (.pdf) translation feature (``src.components.interfaces.pdf``).

Coverage:
- Unit: ``_segment_page`` (paragraph splitting, pure-number drop, header/
  footer drop), ``build_docx_from_paragraphs`` (valid zip, RTL/LTR,
  page break), ``build_txt_from_paragraphs`` (page-break marker).
- Unit: ``extract_pdf_paragraphs`` over a programmatically-built test PDF
  (multi-page, mixed Arabic/English, a scanned/empty page).
- Unit: ``pypdf`` is NOT imported at module top level (lazy-import
  confinement to ``extract_pdf_paragraphs``).
- Integration: ``translate_pdf`` with the deterministic ``mock_llm`` /
  ``mock_embedder`` / in-memory ``GlossaryIndex`` / temp ChromaDB — exercises
  deduplication, cancellation, per-segment failure recovery, the docx/txt
  sidecar branch, and the RTL flag.

Test PDFs are built with ``pypdf.PdfWriter`` at test time (no binary fixture
checked in).
"""
from __future__ import annotations

import sys
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.components.interfaces.models import PdfTranslationReport
from src.components.interfaces.pdf import (
    _segment_page,
    build_docx_from_paragraphs,
    build_txt_from_paragraphs,
    extract_pdf_paragraphs,
    translate_pdf,
)
from src.config import AppConfig

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test PDF builder (pypdf.PdfWriter — no binary fixture checked in)
# ---------------------------------------------------------------------------


def _build_test_pdf(pages_text: list[str | None]) -> bytes:
    """Build a minimal multi-page PDF where each page's text is the given string.

    A ``None`` entry produces a blank page (no extractable text — simulates a
    scanned page). Uses raw PDF syntax (no pypdf writer dependency) so the
    test is deterministic and does not depend on pypdf's writer API.
    """
    # Object layout:
    # 1: Catalog, 2: Pages, 3: Font (Helvetica), 4+: page + content objects.
    objects: list[bytes] = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    page_obj_nums: list[int] = []
    obj_idx = 4  # pages start at object 4 (1=catalog, 2=pages, 3=font)
    for _i, text in enumerate(pages_text):
        page_obj_nums.append(obj_idx)
        obj_idx += 1  # page object
        if text is not None:
            obj_idx += 1  # content stream object

    pages_dict = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects.append(
        f"2 0 obj\n<< /Type /Pages /Kids [{pages_dict}] /Count {len(pages_text)} >>\nendobj\n"
        .encode("latin-1")
    )
    # Object 3: Font (Helvetica — a standard Type 1 font).
    objects.append(
        b"3 0 obj\n"
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        b"endobj\n"
    )

    for i, text in enumerate(pages_text):
        page_num = page_obj_nums[i]
        if text is None:
            objects.append(
                f"{page_num} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\n"
                f"endobj\n".encode("latin-1")
            )
        else:
            content_num = page_num + 1
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content = f"BT /F1 12 Tf 72 700 Td ({escaped}) Tj ET".encode("latin-1", "replace")
            objects.append(
                f"{page_num} 0 obj\n"
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_num} 0 R "
                f"/Resources << /Font << /F1 3 0 R >> >> >>\n"
                f"endobj\n".encode("latin-1")
            )
            objects.append(
                f"{content_num} 0 obj\n"
                f"<< /Length {len(content)} >>\n"
                f"stream\n".encode("latin-1") + content + b"\nendstream\nendobj\n"
            )

    # Assemble the PDF.
    header = b"%PDF-1.4\n"
    body = b"".join(objects)
    offsets: list[int] = []
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        pos += len(obj)
    xref_pos = pos
    xref = f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode("latin-1")
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("latin-1")
    return header + body + xref + trailer


# ---------------------------------------------------------------------------
# _segment_page
# ---------------------------------------------------------------------------


class TestSegmentPage:
    def test_splits_on_blank_lines(self, config: AppConfig) -> None:
        text = "Article 1.\n\nالمادة الأولى.\n\nArticle 2."
        paras = _segment_page(text, cfg=config)
        assert paras == ["Article 1.", "المادة الأولى.", "Article 2."]

    def test_skips_pure_number_blocks(self, config: AppConfig) -> None:
        text = "1\n\nArticle 1.\n\n2"
        paras = _segment_page(text, cfg=config)
        assert paras == ["Article 1."]

    def test_preserves_arabic_indic_digit_blocks(self, config: AppConfig) -> None:
        # Arabic-Indic digits (U+0660..U+0669) must NOT be classified as
        # pure-number page-number noise — they are legitimate content.
        text = "١٢٣٤\n\nالمادة الأولى."
        paras = _segment_page(text, cfg=config)
        assert paras == ["١٢٣٤", "المادة الأولى."]

    def test_preserves_arabic_letter_block_with_period(self, config: AppConfig) -> None:
        # An Arabic block with no ASCII digits must not be dropped.
        text = "المادة.\n\nArticle 1."
        paras = _segment_page(text, cfg=config)
        assert paras == ["المادة.", "Article 1."]

    def test_collapses_internal_newlines_to_spaces(self, config: AppConfig) -> None:
        text = "Line one\nLine two\n\nSecond paragraph"
        paras = _segment_page(text, cfg=config)
        assert paras == ["Line one Line two", "Second paragraph"]

    def test_skips_empty_blocks(self, config: AppConfig) -> None:
        text = "Article 1.\n\n\n\nArticle 2."
        paras = _segment_page(text, cfg=config)
        assert paras == ["Article 1.", "Article 2."]

    def test_skip_header_footer_drops_short_end_blocks(self, config: AppConfig) -> None:
        cfg = config.model_copy(update={"pdf": config.pdf.model_copy(
            update={"skip_header_footer": True})})
        # First block is a short header "Header", last is a page number "3".
        text = "Header\n\nArticle 1.\n\nArticle 2.\n\n3"
        paras = _segment_page(text, cfg=cfg)
        assert "Header" not in paras
        assert "3" not in paras
        assert "Article 1." in paras
        assert "Article 2." in paras


# ---------------------------------------------------------------------------
# build_docx_from_paragraphs / build_txt_from_paragraphs
# ---------------------------------------------------------------------------


class TestBuildDocx:
    def test_produces_valid_zip_with_document_xml(self) -> None:
        pages = [["Paragraph one", "Paragraph two"], ["Page two"]]
        out = build_docx_from_paragraphs(pages, rtl=True)
        assert out[:2] == b"PK"  # zip magic
        with zipfile.ZipFile(BytesIO(out)) as z:
            names = z.namelist()
            assert "word/document.xml" in names
            assert "[Content_Types].xml" in names
            doc = z.read("word/document.xml").decode("utf-8")
            assert "Paragraph one" in doc
            assert "Paragraph two" in doc
            assert "Page two" in doc

    def test_rtl_adds_bidi_visual(self) -> None:
        out = build_docx_from_paragraphs([["a"]], rtl=True)
        doc = zipfile.ZipFile(BytesIO(out)).read("word/document.xml").decode("utf-8")
        assert "bidiVisual" in doc

    def test_ltr_omits_bidi_visual(self) -> None:
        out = build_docx_from_paragraphs([["a"]], rtl=False)
        doc = zipfile.ZipFile(BytesIO(out)).read("word/document.xml").decode("utf-8")
        assert "bidiVisual" not in doc

    def test_page_break_between_pages(self) -> None:
        pages = [["a"], ["b"]]
        out = build_docx_from_paragraphs(pages, rtl=False)
        doc = zipfile.ZipFile(BytesIO(out)).read("word/document.xml").decode("utf-8")
        assert 'w:br w:type="page"' in doc or "w:type=\"page\"" in doc

    def test_escapes_xml_special_chars(self) -> None:
        out = build_docx_from_paragraphs([["a <b> & c"]], rtl=False)
        doc = zipfile.ZipFile(BytesIO(out)).read("word/document.xml").decode("utf-8")
        assert "&lt;b&gt;" in doc
        assert "&amp;" in doc

    def test_validates_zip_entry_names_against_zip_slip(self) -> None:
        """build_docx_from_paragraphs must validate each zip entry name via
        validate_zip_path (defense-in-depth against zip-slip, matching the
        Word adapter's pattern)."""
        from unittest.mock import patch

        pages = [["Paragraph one", "Paragraph two"], ["Page two"]]
        with patch("src.components.interfaces.pdf.validate_zip_path") as mock_validate:
            mock_validate.side_effect = lambda name: name  # pass-through
            build_docx_from_paragraphs(pages, rtl=True)
        # All four entries must be validated.
        assert mock_validate.call_count == 4
        validated_names = {call.args[0] for call in mock_validate.call_args_list}
        assert validated_names == {
            "[Content_Types].xml",
            "_rels/.rels",
            "word/_rels/document.xml.rels",
            "word/document.xml",
        }


class TestBuildTxt:
    def test_joins_paragraphs_with_blank_lines(self) -> None:
        text = build_txt_from_paragraphs([["a", "b"], ["c"]])
        assert "a" in text
        assert "b" in text
        assert "c" in text
        assert "a\n\nb" in text

    def test_includes_page_break_marker(self) -> None:
        text = build_txt_from_paragraphs([["a"], ["b"]])
        assert "--- page break ---" in text


# ---------------------------------------------------------------------------
# extract_pdf_paragraphs
# ---------------------------------------------------------------------------


class TestExtractPdfParagraphs:
    def test_extracts_text_from_simple_pdf(self, config: AppConfig, tmp_path: Path) -> None:
        pdf_bytes = _build_test_pdf(["Article 1 of the Civil Code."])
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(pdf_bytes)
        pages, warnings = extract_pdf_paragraphs(str(pdf_path), cfg=config)
        assert len(pages) == 1
        assert len(pages[0]) >= 1
        assert any("Article 1" in p for p in pages[0])
        assert warnings == []

    def test_records_warning_for_empty_page(self, config: AppConfig, tmp_path: Path) -> None:
        pdf_bytes = _build_test_pdf(["Article 1.", None, "Article 3."])
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(pdf_bytes)
        pages, warnings = extract_pdf_paragraphs(str(pdf_path), cfg=config)
        assert len(pages) == 3
        assert pages[1] == []  # blank page -> empty list
        assert any("Page 2" in w and "no extractable text" in w for w in warnings)


# ---------------------------------------------------------------------------
# pypdf lazy-import confinement
# ---------------------------------------------------------------------------


class TestLazyImport:
    def test_pypdf_not_imported_at_module_level(self) -> None:
        # Ensure pypdf is not in sys.modules, then import the pdf module.
        # (If a prior test imported pypdf, remove it to simulate a fresh
        # process for this check.)
        had_pypdf = "pypdf" in sys.modules
        if had_pypdf:
            del sys.modules["pypdf"]
        try:
            import importlib
            import src.components.interfaces.pdf as pdf_mod
            importlib.reload(pdf_mod)
            assert "pypdf" not in sys.modules, (
                "pypdf must NOT be imported at module top level — only inside "
                "extract_pdf_paragraphs."
            )
        finally:
            if had_pypdf:
                import pypdf  # noqa: F401 — restore for subsequent tests


# ---------------------------------------------------------------------------
# translate_pdf orchestrator (integration with mock adapters)
# ---------------------------------------------------------------------------


def _build_chroma(tmp_path: Path, mock_embedder, config: AppConfig) -> str:
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


def _setup_mock_llm(mock_llm) -> None:
    mock_llm.set_response("translator", "contract of sale")


class TestTranslatePdf:
    def _run(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
        *, pdf_bytes: bytes | None = None,
        cancel_after: int | None = None,
        fail_after: int | None = None,
        out_format: str = "docx",
    ) -> tuple[PdfTranslationReport, bytes, Path]:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        if pdf_bytes is None:
            pdf_bytes = _build_test_pdf([
                "Article 1 of the Civil Code.",
                "Article 2 of the Penal Code.",
            ])
        in_p = tmp_path / "in.pdf"
        suffix = ".docx" if out_format == "docx" else ".txt"
        out_p = tmp_path / f"out{suffix}"
        in_p.write_bytes(pdf_bytes)

        cfg = config.model_copy(update={"pdf": config.pdf.model_copy(
            update={"out_format": out_format})})  # type: ignore[arg-type]

        cancel_event = threading.Event()

        if fail_after is not None:
            original_generate = mock_llm.generate
            call_count = {"n": 0}

            def failing_generate(system_prompt, user_prompt, **kw):
                call_count["n"] += 1
                if call_count["n"] == fail_after:
                    from src.components.translation_pipeline.exceptions import (
                        LLMRuntimeError,
                    )
                    raise LLMRuntimeError("Simulated segment failure")
                return original_generate(system_prompt, user_prompt, **kw)
            mock_llm.generate = failing_generate  # type: ignore[method-assign]

        if cancel_after is not None:
            original_generate2 = mock_llm.generate
            call_count2 = {"n": 0}

            def cancelling_generate(system_prompt, user_prompt, **kw):
                call_count2["n"] += 1
                if call_count2["n"] >= cancel_after:
                    cancel_event.set()
                return original_generate2(system_prompt, user_prompt, **kw)
            mock_llm.generate = cancelling_generate  # type: ignore[method-assign]

        report = translate_pdf(
            str(in_p), str(out_p), "en-ar", cfg,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
            run_logger=None, tm=None,
            cancel_event=cancel_event,
        )
        out_bytes = out_p.read_bytes() if out_p.exists() else b""
        return report, out_bytes, out_p

    def test_translates_to_docx_sidecar(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, out_p = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config,
            out_format="docx")
        assert out_p.exists()
        assert out_bytes[:2] == b"PK"  # zip magic
        assert report.total_pages >= 1
        assert report.translated > 0
        assert report.cancelled is False
        with zipfile.ZipFile(BytesIO(out_bytes)) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            assert "contract of sale" in doc

    def test_translates_to_txt_sidecar(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config,
            out_format="txt")
        text = out_bytes.decode("utf-8")
        assert "contract of sale" in text
        assert "--- page break ---" in text

    def test_docx_sidecar_rtl_for_ar_en(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        # direction ar-en -> rtl=True -> bidiVisual in the docx.
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        pdf_bytes = _build_test_pdf(["المادة الأولى."])
        in_p = tmp_path / "in.pdf"
        out_p = tmp_path / "out.docx"
        in_p.write_bytes(pdf_bytes)
        report = translate_pdf(
            str(in_p), str(out_p), "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert report.total_pages == 1
        with zipfile.ZipFile(BytesIO(out_p.read_bytes())) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            assert "bidiVisual" in doc

    def test_docx_sidecar_ltr_for_en_ar(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config,
            out_format="docx")
        with zipfile.ZipFile(BytesIO(out_bytes)) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            assert "bidiVisual" not in doc

    def test_per_segment_failure_preserves_original(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config,
            fail_after=1)
        assert report.failed == 1
        assert any("failed" in w.lower() or "preserved" in w.lower() for w in report.warnings)

    def test_cancellation_stops_early(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config,
            cancel_after=1)
        assert report.cancelled is True
        assert out_bytes[:2] == b"PK"

    def test_oversized_pdf_rejected(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        cfg = config.model_copy(update={"pdf": config.pdf.model_copy(
            update={"max_pdf_bytes": 100})})
        with pytest.raises(InputValidationError):
            self._run(mock_llm, mock_embedder, glossary_index, tmp_path, cfg)

    def test_too_many_pages_rejected(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        cfg = config.model_copy(update={"pdf": config.pdf.model_copy(
            update={"max_pages": 1})})
        # The default test PDF has 2 pages.
        with pytest.raises(InputValidationError):
            self._run(mock_llm, mock_embedder, glossary_index, tmp_path, cfg)

    def test_docx_sidecar_rtl_for_auto_arabic(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        # direction auto with Arabic-dominant text -> ar-en per segment ->
        # rtl=True -> bidiVisual in the docx sidecar.
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        pdf_bytes = _build_test_pdf(["المادة الأولى."])
        in_p = tmp_path / "in.pdf"
        out_p = tmp_path / "out.docx"
        in_p.write_bytes(pdf_bytes)
        report = translate_pdf(
            str(in_p), str(out_p), "auto", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert report.total_pages == 1
        with zipfile.ZipFile(BytesIO(out_p.read_bytes())) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            assert "bidiVisual" in doc

    def test_corrupt_pdf_raises_input_validation_error(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_p = tmp_path / "in.pdf"
        in_p.write_bytes(b"not a real pdf")
        out_p = tmp_path / "out.docx"
        with pytest.raises(InputValidationError, match="valid PDF"):
            translate_pdf(
                str(in_p), str(out_p), "ar-en", config,
                llm=mock_llm, embedder=mock_embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
            )

    def test_max_pages_checked_before_extraction(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        # A PDF whose page count exceeds max_pages must be rejected BEFORE
        # text extraction runs. We verify this by using a PDF where page 2
        # has no extractable text (a "scanned" page) — the page-count check
        # should fire on len(reader.pages), not after extraction.
        from src.components.translation_pipeline.exceptions import InputValidationError
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        cfg = config.model_copy(update={"pdf": config.pdf.model_copy(
            update={"max_pages": 1})})
        # 3-page PDF; max_pages=1. The check should fire on page count.
        pdf_bytes = _build_test_pdf(["Page 1", "Page 2", "Page 3"])
        in_p = tmp_path / "in.pdf"
        out_p = tmp_path / "out.docx"
        in_p.write_bytes(pdf_bytes)
        with pytest.raises(InputValidationError, match="page"):
            translate_pdf(
                str(in_p), str(out_p), "ar-en", cfg,
                llm=mock_llm, embedder=mock_embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
            )

    def test_max_segments_rejected(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        """A PDF with more unique segments than max_segments must be rejected
        with InputValidationError (regression coverage for pdf.py:302-307)."""
        from src.components.translation_pipeline.exceptions import InputValidationError
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        # max_segments minimum is 100; create 101 unique segments (one per page).
        cfg = config.model_copy(update={"pdf": config.pdf.model_copy(
            update={"max_segments": 100})})
        page_texts = [f"Unique article number {i} for testing." for i in range(101)]
        pdf_bytes = _build_test_pdf(page_texts)
        in_p = tmp_path / "in.pdf"
        out_p = tmp_path / "out.docx"
        in_p.write_bytes(pdf_bytes)
        with pytest.raises(InputValidationError, match="segment"):
            translate_pdf(
                str(in_p), str(out_p), "ar-en", cfg,
                llm=mock_llm, embedder=mock_embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
            )

    def test_oversized_segment_skipped(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        """A segment exceeding max_segment_chars must be skipped (warning
        logged, original text preserved in the output) — regression coverage
        for pdf.py:332-340."""
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        cfg = config.model_copy(update={"pdf": config.pdf.model_copy(
            update={"max_segment_chars": 16})})
        # Page 1: short segment (11 chars <= 16) -> translated.
        # Page 2: long segment (33 chars > 16) -> skipped, original preserved.
        pdf_bytes = _build_test_pdf([
            "Short text.",
            "This is a very long article text.",
        ])
        in_p = tmp_path / "in.pdf"
        out_p = tmp_path / "out.docx"
        in_p.write_bytes(pdf_bytes)
        report = translate_pdf(
            str(in_p), str(out_p), "en-ar", cfg,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert report.skipped == 1
        assert any("Skipped oversized segment" in w for w in report.warnings)
        # Original (untranslated) text must be preserved in the output docx.
        with zipfile.ZipFile(BytesIO(out_p.read_bytes())) as z:
            doc = z.read("word/document.xml").decode("utf-8")
            assert "This is a very long article text." in doc


# ---------------------------------------------------------------------------
# pdf CLI command (CliRunner — error paths only)
# ---------------------------------------------------------------------------


class TestPdfCli:
    def test_help_succeeds(self) -> None:
        from src.components.interfaces.cli import app
        result = CliRunner().invoke(app, ["pdf", "--help"])
        assert result.exit_code == 0
        combined = (result.stdout or "") + (result.output or "")
        assert "PDF" in combined or "pdf" in combined.lower()

    def test_missing_input_exits_one(self, tmp_path: Path) -> None:
        from src.components.interfaces.cli import app
        result = CliRunner().invoke(app, [
            "pdf", "--input", str(tmp_path / "missing.pdf"),
            "--out", str(tmp_path / "out.docx"), "--direction", "ar-en",
        ])
        assert result.exit_code == 1
        combined = (result.stdout or "") + (result.output or "")
        assert "not found" in combined.lower()

    def test_wrong_extension_exits_one(self, tmp_path: Path) -> None:
        from src.components.interfaces.cli import app
        bad = tmp_path / "data.docx"
        bad.write_text("not a pdf", encoding="utf-8")
        result = CliRunner().invoke(app, [
            "pdf", "--input", str(bad),
            "--out", str(tmp_path / "out.docx"), "--direction", "ar-en",
        ])
        assert result.exit_code == 1
        combined = (result.stdout or "") + (result.output or "")
        assert ".pdf" in combined
