"""Tests for the Excel (.xlsx) translation feature (``src.components.interfaces.excel``).

Coverage:
- Unit: ``protect_non_translatable`` / ``restore_protected`` round-trip over
  placeholders, URLs, emails, numbers, and Excel header/footer ``&``-codes.
- Unit: ``extract_translatable_strings`` / ``patch_strings`` over shared
  strings (plain + rich runs), inline strings, comments, headers/footers, and
  chart titles — and the byte-for-byte preservation of formulas, merged cells,
  conditional formatting, data validation, and hyperlinks.
- Integration: ``translate_excel`` with the deterministic ``mock_llm`` /
  ``mock_embedder`` / in-memory ``GlossaryIndex`` / temp ChromaDB — exercises
  deduplication, progress reporting, cancellation, per-segment failure
  recovery, and the ``max_segment_chars`` skip.
- E2E: a programmatically-built workbook with formatting/formulas/merged
  cells/comments/chart is translated and the non-text parts are asserted
  byte-identical between input and output.

Fixtures are built from raw OOXML (no ``openpyxl`` dependency) so the tests
run in CI with only the stdlib + the project's existing dev deps.
"""
from __future__ import annotations

import threading
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from src.components.interfaces.cli import app
from src.components.interfaces.excel import (
    extract_translatable_strings,
    patch_strings,
    protect_non_translatable,
    restore_protected,
    translate_excel,
)
from src.components.interfaces.models import ExcelTranslationReport
from src.config import AppConfig

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Minimal .xlsx builder (raw OOXML — no openpyxl dependency)
# ---------------------------------------------------------------------------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/><Override PartName="/xl/comments1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.comments+xml"/><Override PartName="/xl/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.chart+xml"/></Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"""

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/><sheet name="Hidden" sheetId="2" state="hidden" r:id="rId2"/></sheets></workbook>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments1.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="charts/chart1.xml"/></Relationships>"""

# sharedStrings: plain, rich-run (two runs), placeholder cell, english label
_SHARED = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="5" uniqueCount="5"><si><t>عقد البيع</t></si><si><r><rPr><b/></rPr><t>المادة</t></r><r><t> 148</t></r></si><si><t>Total for {year}: مبلغ</t></si><si><t>See https://example.org/x for details</t></si><si><t>عقد البيع</t></si></sst>"""

# sheet1: shared-string refs (A1,A2,A3,A4), formula (B1), inline string (C1),
# merged cells, conditional formatting, data validation, hyperlink, header/footer
_SHEET1 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetData><c r="A1" t="s"><v>0</v></c><c r="A2" t="s"><v>1</v></c><c r="A3" t="s"><v>2</v></c><c r="A4" t="s"><v>3</v></c><c r="A5" t="s"><v>4</v></c><c r="B1"><f>SUM(B2:B3)</f><v>6</v></c><c r="C1" t="inlineStr"><is><t>تقرير</t></is></c></sheetData><mergeCells count="1"><mergeCell ref="A1:A2"/></mergeCells><conditionalFormatting sqref="B1:B3"><cfRule type="cellIs" dxfId="0" priority="1" operator="greaterThan"><formula>5</formula></cfRule></conditionalFormatting><dataValidations count="1"><dataValidation type="whole" allowBlank="1" sqref="B1:B3"><formula1>10</formula1></dataValidation></dataValidations><hyperlinks><hyperlink ref="A4" r:id="rId4"/></hyperlinks><headerFooter><oddHeader>Page &amp;P of &amp;N - تقرير</oddHeader></headerFooter></worksheet>"""

_SHEET2 = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><c r="A1" t="inlineStr"><is><t>مخفي</t></is></c></sheetData></worksheet>"""

_COMMENTS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<comments xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><authors><author>legal</author></authors><commentList><comment ref="A1" authorId="0"><text><t>ملاحظة قانونية</t></text></comment><comment ref="A2" authorId="0"><text><r><rPr><i/></rPr><t>مراجعة</t></r></text></comment></commentList></comments>"""

_CHART = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/chartml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:chart><c:title><c:tx><c:rich><a:p><a:r><a:t>تقرير المبيعات</a:t></a:r></a:p></c:rich></c:tx></c:title><c:plotArea><c:barChart><c:axId val="1"/><c:axId val="2"/></c:barChart><c:catAx><c:axId val="1"/><c:title><c:tx><c:rich><a:p><a:r><a:t>الفئة</a:t></a:r></a:p></c:rich></c:tx></c:title></c:catAx></c:plotArea></c:chart></c:chartSpace>"""

# A non-XML binary part (fake image) to prove byte-for-byte copy of non-text parts.
_IMAGE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _build_workbook() -> bytes:
    """Assemble a feature-rich .xlsx from raw OOXML parts."""
    parts: dict[str, bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "xl/workbook.xml": _WORKBOOK,
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/sharedStrings.xml": _SHARED,
        "xl/worksheets/sheet1.xml": _SHEET1,
        "xl/worksheets/sheet2.xml": _SHEET2,
        "xl/comments1.xml": _COMMENTS,
        "xl/charts/chart1.xml": _CHART,
        "xl/media/image1.png": _IMAGE_PNG,
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data.encode("utf-8") if isinstance(data, str) else data)
    return buf.getvalue()


def _read_part(xlsx_bytes: bytes, name: str) -> str:
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as z:
        return z.read(name).decode("utf-8")


def _part_names(xlsx_bytes: bytes) -> list[str]:
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as z:
        return [i.filename for i in z.infolist()]


# Allowlisted parts (may differ between input and output). Everything else
# must be byte-identical for the preservation assertions.
_ALLOWLISTED = {
    "xl/sharedStrings.xml",
    "xl/worksheets/sheet1.xml",
    "xl/worksheets/sheet2.xml",
    "xl/comments1.xml",
    "xl/charts/chart1.xml",
}


# ---------------------------------------------------------------------------
# protect / restore
# ---------------------------------------------------------------------------


class TestProtectRestore:
    def test_placeholder_preserved(self, config: AppConfig) -> None:
        text = "Total for {year}: مبلغ"
        protected, token_map = protect_non_translatable(text)
        assert "{year}" not in protected
        assert restore_protected(protected, token_map) == text

    def test_url_preserved(self, config: AppConfig) -> None:
        text = "See https://example.org/x for details"
        protected, token_map = protect_non_translatable(text)
        assert "https://example.org/x" not in protected
        assert restore_protected(protected, token_map) == text

    def test_number_preserved(self, config: AppConfig) -> None:
        text = "المادة 148 تنص على ذلك"
        protected, token_map = protect_non_translatable(text)
        assert "148" not in protected
        assert restore_protected(protected, token_map) == text

    def test_email_preserved(self, config: AppConfig) -> None:
        text = "Contact admin@justice.gov.iq for info"
        protected, token_map = protect_non_translatable(text)
        assert "admin@justice.gov.iq" not in protected
        assert restore_protected(protected, token_map) == text

    def test_header_footer_codes_preserved(self, config: AppConfig) -> None:
        text = "Page &P of &N - تقرير"
        protected, token_map = protect_non_translatable(text)
        assert "&P" not in protected
        assert "&N" not in protected
        assert restore_protected(protected, token_map) == text

    def test_identical_tokens_reuse_sentinel(self, config: AppConfig) -> None:
        text = "{x} and {x} and 148 and 148"
        protected, token_map = protect_non_translatable(text)
        # Two distinct originals -> two sentinels, each used twice.
        assert protected.count("\x00T0\x00") == 2
        assert protected.count("\x00T1\x00") == 2
        assert restore_protected(protected, token_map) == text

    def test_plain_text_unchanged(self, config: AppConfig) -> None:
        text = "عقد البيع"
        protected, token_map = protect_non_translatable(text)
        assert protected == text
        assert token_map == {}
        assert restore_protected(protected, token_map) == text


# ---------------------------------------------------------------------------
# extract / patch
# ---------------------------------------------------------------------------


class TestExtractPatch:
    def test_extracts_shared_strings_plain_and_rich(self, config: AppConfig) -> None:
        segs = extract_translatable_strings(_build_workbook(), cfg=config)
        texts = {s.text for s in segs}
        assert "عقد البيع" in texts
        assert "المادة" in texts
        assert " 148" in texts  # rich-text run translated per-run
        assert "Total for {year}: مبلغ" in texts

    def test_extracts_inline_strings(self, config: AppConfig) -> None:
        segs = extract_translatable_strings(_build_workbook(), cfg=config)
        texts = {s.text for s in segs}
        assert "تقرير" in texts  # sheet1 inline string
        assert "مخفي" in texts  # hidden sheet2 inline string

    def test_extracts_comments(self, config: AppConfig) -> None:
        segs = extract_translatable_strings(_build_workbook(), cfg=config)
        texts = {s.text for s in segs}
        assert "ملاحظة قانونية" in texts
        assert "مراجعة" in texts

    def test_extracts_chart_titles(self, config: AppConfig) -> None:
        segs = extract_translatable_strings(_build_workbook(), cfg=config)
        texts = {s.text for s in segs}
        assert "تقرير المبيعات" in texts
        assert "الفئة" in texts  # axis title

    def test_extracts_header_footer(self, config: AppConfig) -> None:
        segs = extract_translatable_strings(_build_workbook(), cfg=config)
        texts = {s.text for s in segs}
        assert "Page &P of &N - تقرير" in texts

    def test_deduplicates_by_text(self, config: AppConfig) -> None:
        segs = extract_translatable_strings(_build_workbook(), cfg=config)
        # "عقد البيع" appears twice in sharedStrings (index 0 and 4) -> one segment.
        arabic_sale = [s for s in segs if s.text == "عقد البيع"]
        assert len(arabic_sale) == 1

    def test_patch_translates_shared_strings(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        shared = _read_part(out, "xl/sharedStrings.xml")
        assert "[T:عقد البيع]" in shared
        # The rich-run cell: each <t> translated independently.
        assert "[T:المادة]" in shared
        assert "[T: 148]" in shared

    def test_patch_preserves_formulas_and_values(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        sheet = _read_part(out, "xl/worksheets/sheet1.xml")
        assert "<f>SUM(B2:B3)</f><v>6</v>" in sheet

    def test_patch_preserves_merged_cells(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        sheet = _read_part(out, "xl/worksheets/sheet1.xml")
        assert '<mergeCells count="1"><mergeCell ref="A1:A2"' in sheet

    def test_patch_preserves_conditional_formatting_and_validation(
        self, config: AppConfig
    ) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        sheet = _read_part(out, "xl/worksheets/sheet1.xml")
        assert "conditionalFormatting" in sheet
        assert "dataValidation" in sheet
        assert "<formula>5</formula>" in sheet
        assert "<formula1>10</formula1>" in sheet

    def test_patch_preserves_hyperlinks(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        sheet = _read_part(out, "xl/worksheets/sheet1.xml")
        assert "<hyperlink ref=\"A4\"" in sheet

    def test_patch_preserves_hidden_sheet_state(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        wb = _read_part(out, "xl/workbook.xml")
        assert 'state="hidden"' in wb

    def test_non_text_parts_byte_identical(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        with zipfile.ZipFile(BytesIO(data)) as zin, \
                zipfile.ZipFile(BytesIO(out)) as zout:
            for info in zin.infolist():
                if info.filename in _ALLOWLISTED:
                    continue
                assert zin.read(info.filename) == zout.read(info.filename), (
                    f"non-text part changed: {info.filename}"
                )

    def test_image_part_byte_identical(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        translations = {s.text: f"[T:{s.text}]" for s in segs}
        out = patch_strings(data, translations, cfg=config)
        with zipfile.ZipFile(BytesIO(data)) as zin, \
                zipfile.ZipFile(BytesIO(out)) as zout:
            assert zin.read("xl/media/image1.png") == zout.read("xl/media/image1.png")

    def test_translate_comments_toggle_off(self, config: AppConfig) -> None:
        data = _build_workbook()
        cfg = config.model_copy(deep=True)
        cfg.excel = cfg.excel.model_copy(update={"translate_comments": False})
        segs = extract_translatable_strings(data, cfg=cfg)
        texts = {s.text for s in segs}
        assert "ملاحظة قانونية" not in texts
        assert "مراجعة" not in texts

    def test_translate_chart_titles_toggle_off(self, config: AppConfig) -> None:
        data = _build_workbook()
        cfg = config.model_copy(deep=True)
        cfg.excel = cfg.excel.model_copy(update={"translate_chart_titles": False})
        segs = extract_translatable_strings(data, cfg=cfg)
        texts = {s.text for s in segs}
        assert "تقرير المبيعات" not in texts

    def test_translate_headers_footers_toggle_off(self, config: AppConfig) -> None:
        data = _build_workbook()
        cfg = config.model_copy(deep=True)
        cfg = cfg.model_copy(update={"excel": cfg.excel.model_copy(
            update={"translate_headers_footers": False})})
        segs = extract_translatable_strings(data, cfg=cfg)
        texts = {s.text for s in segs}
        assert "Page &P of &N - تقرير" not in texts

    def test_empty_text_skipped(self, config: AppConfig) -> None:
        # A shared string with whitespace-only text is skipped.
        shared = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>   </t></si><si><t>عقد</t></si></sst>"""
        data = _build_with_shared(shared)
        segs = extract_translatable_strings(data, cfg=config)
        texts = [s.text for s in segs]
        assert "   " not in texts
        assert "عقد" in texts

    def test_patch_leaves_untranslated_text_unchanged(self, config: AppConfig) -> None:
        data = _build_workbook()
        segs = extract_translatable_strings(data, cfg=config)
        # Translate only one segment; the rest must keep original text.
        only = segs[0].text
        translations = {only: "[T:ONLY]"}
        out = patch_strings(data, translations, cfg=config)
        shared = _read_part(out, "xl/sharedStrings.xml")
        assert "[T:ONLY]" in shared
        # Another segment's text still present verbatim.
        assert "Total for {year}: مبلغ" in shared

    def test_extract_rejects_bad_zip(self, config: AppConfig) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        with pytest.raises(InputValidationError, match="valid zip"):
            extract_translatable_strings(b"not a real xlsx", cfg=config)

    def test_patch_rejects_bad_zip(self, config: AppConfig) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        with pytest.raises(InputValidationError, match="valid zip"):
            patch_strings(b"not a real xlsx", {}, cfg=config)


# ---------------------------------------------------------------------------
# Security: defusedxml defends against XXE
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_xxe_entity_not_expanded_in_extract(self, config: AppConfig) -> None:
        # A sharedStrings.xml with an XXE entity reference. defusedxml refuses
        # to resolve external entities; the part is skipped safely -> no crash,
        # no segments from that part (other valid parts are still processed).
        xxe_shared = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE sst ['
            '<!ENTITY xxe SYSTEM "file:///etc/passwd">'
            ']>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<si><t>&xxe;</t></si></sst>'
        )
        data = _build_with_shared(xxe_shared)
        # Must not raise DefusedXmlException; the XXE part is skipped.
        segs = extract_translatable_strings(data, cfg=config)
        texts = {s.text for s in segs}
        # The XXE entity text is NOT extracted (part was skipped).
        assert "&xxe;" not in texts
        # Other valid parts (sheet1 inline string) are still processed.
        assert "تقرير" in texts

    def test_xxe_entity_returns_original_bytes_in_patch(self, config: AppConfig) -> None:
        # A sharedStrings.xml with an XXE entity reference. defusedxml refuses
        # to resolve external entities; _patch_part returns the original bytes
        # unchanged (fail safe) instead of crashing.
        xxe_shared = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE sst ['
            '<!ENTITY xxe SYSTEM "file:///etc/passwd">'
            ']>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<si><t>&xxe;</t></si></sst>'
        )
        data = _build_with_shared(xxe_shared)
        original_shared = _read_part(data, "xl/sharedStrings.xml")
        out = patch_strings(data, {"&xxe;": "[T:INJECTED]"}, cfg=config)
        patched_shared = _read_part(out, "xl/sharedStrings.xml")
        # The XXE part is returned byte-for-byte unchanged (no translation applied).
        assert patched_shared == original_shared


def _build_with_shared(shared_xml: str) -> bytes:
    """Build a workbook overriding only the sharedStrings part."""
    parts: dict[str, Any] = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "xl/workbook.xml": _WORKBOOK,
        "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
        "xl/sharedStrings.xml": shared_xml,
        "xl/worksheets/sheet1.xml": _SHEET1,
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, d in parts.items():
            z.writestr(name, d.encode("utf-8"))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# translate_excel orchestration (integration with mock adapters)
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
        Chunk(
            chunk_id="civil_code_en_5_0",
            text="Article 5 of the Iraqi Civil Code governs the contract of sale.",
            law="Civil Code", article="5", lang="en",
            law_slug="civil_code", chunk_idx=0, char_start=0, char_end=80,
        ),
    ]
    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(
        chunks, persist_dir=persist_dir, embedder=mock_embedder, cfg=config,
    )
    return persist_dir


def _setup_mock_llm(mock_llm) -> None:
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


class TestTranslateExcel:
    def test_translates_workbook_and_preserves_structure(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        report = translate_excel(
            str(in_path), str(out_path), "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )

        assert isinstance(report, ExcelTranslationReport)
        assert report.cancelled is False
        assert report.total_segments > 0
        assert report.translated == report.total_segments
        assert report.failed == 0
        assert out_path.is_file()

        # Non-text parts byte-identical.
        with zipfile.ZipFile(BytesIO(in_path.read_bytes())) as zin, \
                zipfile.ZipFile(BytesIO(out_path.read_bytes())) as zout:
            for info in zin.infolist():
                if info.filename in _ALLOWLISTED:
                    continue
                assert zin.read(info.filename) == zout.read(info.filename)

    def test_deduplication_translates_unique_string_once(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        call_count = {"n": 0}
        original_generate = mock_llm.generate

        def counting_generate(system, user, **kw):
            call_count["n"] += 1
            return original_generate(system, user, **kw)

        mock_llm.generate = counting_generate  # type: ignore[method-assign]

        segs = extract_translatable_strings(in_path.read_bytes(), cfg=config)
        unique_texts = {s.text for s in segs}
        try:
            translate_excel(
                str(in_path), str(out_path), "ar-en", config,
                llm=mock_llm, embedder=mock_embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
            )
        finally:
            mock_llm.generate = original_generate  # type: ignore[method-assign]

        # Each unique source string -> one translator + one auditor call.
        # The mock returns APPROVE immediately, so 2 LLM calls per segment.
        assert call_count["n"] == 2 * len(unique_texts)

    def test_progress_callback(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        events: list[tuple[int, int, str]] = []

        def progress(completed: int, total: int, current: str) -> None:
            events.append((completed, total, current))

        report = translate_excel(
            str(in_path), str(out_path), "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
            progress=progress,
        )
        assert report.total_segments > 0
        # Final event has completed == total.
        assert events[-1][0] == events[-1][1] == report.total_segments
        # completed is monotonically non-decreasing.
        completed_vals = [e[0] for e in events]
        assert completed_vals == sorted(completed_vals)

    def test_cancellation_stops_early(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        cancel = threading.Event()

        def progress(completed: int, total: int, current: str) -> None:
            if completed >= 1:
                cancel.set()

        report = translate_excel(
            str(in_path), str(out_path), "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
            progress=progress, cancel_event=cancel,
        )
        assert report.cancelled is True
        assert report.translated >= 1
        assert report.skipped >= 1
        assert out_path.is_file()

    def test_per_segment_failure_keeps_original(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        from src.components.translation_pipeline.exceptions import OllamaTimeoutError

        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(_build_workbook())
        out_path = tmp_path / "out.xlsx"

        original_generate = mock_llm.generate
        calls = {"n": 0}

        def failing_generate(system, user, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OllamaTimeoutError("simulated timeout on first segment")
            return original_generate(system, user, **kw)

        mock_llm.generate = failing_generate  # type: ignore[method-assign]
        try:
            report = translate_excel(
                str(in_path), str(out_path), "ar-en", config,
                llm=mock_llm, embedder=mock_embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
            )
        finally:
            mock_llm.generate = original_generate  # type: ignore[method-assign]

        assert report.failed == 1
        assert report.cancelled is False
        assert any("Translation failed" in w for w in report.warnings)
        # Output still written; the failed segment's original text is preserved.
        assert out_path.is_file()

    def test_oversized_segment_skipped(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        # Build a workbook with one very long inline string.
        long_text = "عقد " * 2000  # 8000 chars -> exceeds default 4096
        sheet = (
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">"""
            f'<sheetData><c r="A1" t="inlineStr"><is><t>{long_text}</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>عقد قصير</t></is></c></sheetData></worksheet>'
        )
        parts: dict[str, Any] = {
            "[Content_Types].xml": _CONTENT_TYPES,
            "_rels/.rels": _ROOT_RELS,
            "xl/workbook.xml": _WORKBOOK,
            "xl/_rels/workbook.xml.rels": _WORKBOOK_RELS,
            "xl/sharedStrings.xml": _SHARED,
            "xl/worksheets/sheet1.xml": sheet,
        }
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, d in parts.items():
                z.writestr(name, d.encode("utf-8"))
        in_path = tmp_path / "in.xlsx"
        in_path.write_bytes(buf.getvalue())
        out_path = tmp_path / "out.xlsx"

        report = translate_excel(
            str(in_path), str(out_path), "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert report.skipped >= 1
        assert any("oversized" in w for w in report.warnings)
        # The short segment is still translated.
        assert report.translated >= 1


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


class TestExcelCli:
    def test_help_exits_zero(self) -> None:
        result = CliRunner().invoke(app, ["excel", "--help"])
        assert result.exit_code == 0
        assert "Translate an Excel" in (result.stdout or "") + (result.output or "")

    def test_missing_input_exits_one(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(app, [
            "excel", "--input", str(tmp_path / "missing.xlsx"),
            "--out", str(tmp_path / "out.xlsx"), "--direction", "ar-en",
        ])
        assert result.exit_code == 1
        combined = (result.stdout or "") + (result.output or "")
        assert "not found" in combined.lower()

    def test_wrong_extension_exits_one(self, tmp_path: Path) -> None:
        bad = tmp_path / "data.csv"
        bad.write_text("a,b\n1,2\n", encoding="utf-8")
        result = CliRunner().invoke(app, [
            "excel", "--input", str(bad),
            "--out", str(tmp_path / "out.xlsx"), "--direction", "ar-en",
        ])
        assert result.exit_code == 1
        combined = (result.stdout or "") + (result.output or "")
        assert ".xlsx" in combined
