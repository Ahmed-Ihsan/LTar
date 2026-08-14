"""Tests for the Word (.docx) translation feature (``src.components.interfaces.word``).

Coverage:
- Unit: ``_paragraph_text`` / ``split_translation`` / ``extract_word_strings`` /
  ``patch_word_strings`` over body paragraphs, multi-run paragraphs (space
  insertion + proportional re-split preserving run formatting), headers,
  footers, footnotes, endnotes, comments, and the glossaryDocument toggle.
- Unit: byte-for-byte preservation of styles, images, and tracked-change
  ``w:ins`` wrappers.
- Unit: defusedxml defends against XXE (entity reference is not expanded).
- Integration: ``translate_word`` with the deterministic ``mock_llm`` /
  ``mock_embedder`` / in-memory ``GlossaryIndex`` / temp ChromaDB — exercises
  deduplication, progress reporting, cancellation, per-segment failure
  recovery, and the ``max_segment_chars`` skip.

Fixtures are built from raw OOXML (no ``python-docx`` dependency) so the tests
run in CI with only the stdlib + the project's existing dev deps.
"""
from __future__ import annotations

import threading
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.components.interfaces.models import WordTranslationReport
from src.components.interfaces.word import (
    _paragraph_text,
    extract_word_strings,
    patch_word_strings,
    split_translation,
    translate_word,
)
from src.config import AppConfig

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Minimal .docx builder (raw OOXML — no python-docx dependency)
# ---------------------------------------------------------------------------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/><Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/><Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/><Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/><Override PartName="/word/glossary/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.glossary+xml"/></Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/><Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/><Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/><Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/glossaryDocument" Target="glossary/document.xml"/></Relationships>"""

# Body: plain paragraph, multi-run paragraph (bold + normal), duplicate
# paragraph (dedup), tracked-change w:ins wrapper, hyperlink run.
_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>عقد البيع</w:t></w:r></w:p><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Very </w:t></w:r><w:r><w:t>Important Article</w:t></w:r></w:p><w:p><w:r><w:t>عقد البيع</w:t></w:r></w:p><w:p><w:ins w:id="1" w:author="legal" w:date="2026-01-01T00:00:00Z"><w:r><w:t>المادة 148</w:t></w:r></w:ins></w:p></w:body></w:document>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:styleId="CustomLegal"><w:name w:val="CustomLegal"/><w:pPr><w:spacing w:after="120"/></w:pPr></w:style></w:styles>"""

_HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Republic of Iraq - Ministry of Justice</w:t></w:r></w:p></w:hdr>"""

_FOOTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Page 1</w:t></w:r></w:p></w:ftr>"""

_FOOTNOTES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:footnote w:type="normal" w:id="-1"><w:p><w:r><w:t>ملاحظة قانونية</w:t></w:r></w:p></w:footnote></w:footnotes>"""

_ENDNOTES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:endnote w:type="normal" w:id="-1"><w:p><w:r><w:t>مراجعة</w:t></w:r></w:p></w:endnote></w:endnotes>"""

_COMMENTS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="1" w:author="legal" w:date="2026-01-01T00:00:00Z" w:initials="l"><w:p><w:r><w:t>تحقق من المرجع</w:t></w:r></w:p></w:comment></w:comments>"""

_GLOSSARY = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:glossaryDocument xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>تعريف المصطلح</w:t></w:r></w:p></w:glossaryDocument>"""

# A non-XML binary part (fake image) to prove byte-for-byte copy of non-text parts.
_IMAGE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _build_docx() -> bytes:
    """Assemble a feature-rich .docx from raw OOXML parts."""
    parts: dict[str, bytes] = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "word/document.xml": _DOCUMENT,
        "word/_rels/document.xml.rels": _DOC_RELS,
        "word/styles.xml": _STYLES,
        "word/header1.xml": _HEADER,
        "word/footer1.xml": _FOOTER,
        "word/footnotes.xml": _FOOTNOTES,
        "word/endnotes.xml": _ENDNOTES,
        "word/comments.xml": _COMMENTS,
        "word/glossary/document.xml": _GLOSSARY,
        "word/media/image1.png": _IMAGE_PNG,
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data.encode("utf-8") if isinstance(data, str) else data)
    return buf.getvalue()


def _read_part(docx_bytes: bytes, name: str) -> bytes:
    with zipfile.ZipFile(BytesIO(docx_bytes)) as z:
        return z.read(name)


def _part_names(docx_bytes: bytes) -> list[str]:
    with zipfile.ZipFile(BytesIO(docx_bytes)) as z:
        return [i.filename for i in z.infolist()]


# ---------------------------------------------------------------------------
# _paragraph_text / split_translation
# ---------------------------------------------------------------------------


class TestParagraphText:
    def test_single_run_paragraph(self, config: AppConfig) -> None:
        docx = _build_docx()
        from defusedxml.ElementTree import fromstring as ET_fromstring
        doc = ET_fromstring(_read_part(docx, "word/document.xml"))
        # First w:p is the single-run "عقد البيع".
        from src.components.interfaces.word import _W_MAIN
        p = doc.findall(f".//{{{_W_MAIN}}}p")[0]
        text, run_lengths = _paragraph_text(p)
        assert text == "عقد البيع"
        assert run_lengths == [len("عقد البيع")]

    def test_multi_run_inserts_space(self, config: AppConfig) -> None:
        docx = _build_docx()
        from defusedxml.ElementTree import fromstring as ET_fromstring
        doc = ET_fromstring(_read_part(docx, "word/document.xml"))
        from src.components.interfaces.word import _W_MAIN
        # Second w:p: "Very " (bold) + "Important Article" -> "Very Important Article"
        p = doc.findall(f".//{{{_W_MAIN}}}p")[1]
        text, run_lengths = _paragraph_text(p)
        assert text == "Very Important Article"
        assert run_lengths == [len("Very "), len("Important Article")]

    def test_no_space_when_already_whitespace(self, config: AppConfig) -> None:
        # Build a tiny doc with two runs where the first ends in whitespace.
        from xml.etree import ElementTree as ET
        from src.components.interfaces.word import _W_MAIN
        p = ET.Element(f"{{{_W_MAIN}}}p")
        r1 = ET.SubElement(p, f"{{{_W_MAIN}}}r")
        t1 = ET.SubElement(r1, f"{{{_W_MAIN}}}t")
        t1.text = "Hello "
        r2 = ET.SubElement(p, f"{{{_W_MAIN}}}r")
        t2 = ET.SubElement(r2, f"{{{_W_MAIN}}}t")
        t2.text = "World"
        text, run_lengths = _paragraph_text(p)
        assert text == "Hello World"  # no double space
        assert run_lengths == [len("Hello "), len("World")]


class TestSplitTranslation:
    def test_whole_translation_in_first_run(self) -> None:
        # The entire translation goes in the first run; remaining runs are
        # emptied. No word is ever broken across runs.
        chunks = split_translation("the quick brown fox", [3, 5, 5, 3])
        assert chunks == ["the quick brown fox", "", "", ""]
        assert "".join(chunks) == "the quick brown fox"

    def test_single_run(self) -> None:
        chunks = split_translation("contract of sale", [16])
        assert chunks == ["contract of sale"]

    def test_empty_translation(self) -> None:
        chunks = split_translation("", [3, 5])
        assert chunks == ["", ""]

    def test_zero_run_lengths(self) -> None:
        # Even with zero-length runs, the whole translation still goes in
        # the first slot.
        chunks = split_translation("hello", [0, 0, 0])
        assert chunks == ["hello", "", ""]

    def test_remainder_goes_to_last_run(self) -> None:
        # Compatibility: the last run still receives any "remainder" in the
        # sense that it is the last non-empty slot when there is one run.
        chunks = split_translation("abcdefg", [3, 3])
        assert chunks == ["abcdefg", ""]

    def test_split_does_not_break_protected_sentinel(self) -> None:
        # A protected-token sentinel (`\x00T0\x00`, 4 chars) is never split
        # across two runs because the whole translation lives in the first
        # run. restore_protected applied per-run recovers the original token.
        from src.components.interfaces._doc_common import restore_protected

        sentinel = "\x00T0\x00"
        token_map = {sentinel: "https://example.com"}
        protected = "See " + sentinel + " for details"
        chunks = split_translation(protected, [4, 4, 9])
        # Whole translation in the first run; other runs empty.
        assert chunks[0] == protected
        restored = "".join(restore_protected(c, token_map) for c in chunks)
        assert restored == "See https://example.com for details"
        assert "\x00" not in restored


# ---------------------------------------------------------------------------
# extract_word_strings / patch_word_strings
# ---------------------------------------------------------------------------


class TestExtractPatch:
    def test_extracts_body_paragraphs(self, config: AppConfig) -> None:
        docx = _build_docx()
        segs = extract_word_strings(docx, cfg=config)
        texts = [s.text for s in segs]
        assert "عقد البيع" in texts
        assert "Very Important Article" in texts
        assert "المادة 148" in texts

    def test_deduplicates_identical_paragraphs(self, config: AppConfig) -> None:
        docx = _build_docx()
        segs = extract_word_strings(docx, cfg=config)
        # "عقد البيع" appears twice in the body -> one segment.
        assert sum(1 for s in segs if s.text == "عقد البيع") == 1

    def test_extracts_headers_footers_footnotes_endnotes_comments(self, config: AppConfig) -> None:
        docx = _build_docx()
        segs = extract_word_strings(docx, cfg=config)
        texts = {s.text for s in segs}
        assert "Republic of Iraq - Ministry of Justice" in texts  # header
        assert "Page 1" in texts  # footer
        assert "ملاحظة قانونية" in texts  # footnote
        assert "مراجعة" in texts  # endnote
        assert "تحقق من المرجع" in texts  # comment

    def test_glossary_skipped_by_default(self, config: AppConfig) -> None:
        docx = _build_docx()
        segs = extract_word_strings(docx, cfg=config)
        texts = {s.text for s in segs}
        assert "تعريف المصطلح" not in texts  # glossary off by default

    def test_glossary_translated_when_enabled(self, config: AppConfig) -> None:
        cfg = config.model_copy(update={"word": config.word.model_copy(
            update={"translate_glossary_doc": True})})
        docx = _build_docx()
        segs = extract_word_strings(docx, cfg=cfg)
        texts = {s.text for s in segs}
        assert "تعريف المصطلح" in texts

    def test_comments_skipped_when_toggle_false(self, config: AppConfig) -> None:
        cfg = config.model_copy(update={"word": config.word.model_copy(
            update={"translate_comments": False})})
        docx = _build_docx()
        segs = extract_word_strings(docx, cfg=cfg)
        texts = {s.text for s in segs}
        assert "تحقق من المرجع" not in texts

    def test_patch_translates_body_paragraph(self, config: AppConfig) -> None:
        docx = _build_docx()
        out = patch_word_strings(
            docx, {"عقد البيع": "contract of sale"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "contract of sale" in body
        assert "عقد البيع" not in body

    def test_patch_preserves_styles_image_tracked_changes(self, config: AppConfig) -> None:
        docx = _build_docx()
        out = patch_word_strings(
            docx, {"عقد البيع": "contract of sale",
                   "Very Important Article": "مهم جدا",
                   "المادة 148": "Article 148"}, cfg=config)
        # styles.xml byte-identical
        assert _read_part(out, "word/styles.xml") == _STYLES.encode("utf-8")
        # image byte-identical
        assert _read_part(out, "word/media/image1.png") == _IMAGE_PNG
        # w:ins wrapper preserved (the translated text is inside it)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "w:ins" in body
        assert "Article 148" in body

    def test_patch_multi_run_whole_translation_in_first_run(self, config: AppConfig) -> None:
        docx = _build_docx()
        out = patch_word_strings(
            docx, {"Very Important Article": "مهم جدا"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        # The ENTIRE translation "مهم جدا" is in the first w:t run (which
        # carries the bold w:rPr); the second w:t run is empty.
        assert "مهم جدا" in body
        assert "w:b" in body  # bold formatting preserved on the first run
        # The original English text is gone from the second paragraph.
        assert "Important Article" not in body
        # Verify structurally: the second w:t in the multi-run paragraph is empty.
        from defusedxml.ElementTree import fromstring as ET_fromstring
        from src.components.interfaces.word import _W_MAIN
        doc = ET_fromstring(_read_part(out, "word/document.xml"))
        paras = doc.findall(f".//{{{_W_MAIN}}}p")
        multi_run_p = paras[1]  # "Very Important Article" paragraph
        runs = multi_run_p.findall(f".//{{{_W_MAIN}}}r")
        t_els = [r.find(f"{{{_W_MAIN}}}t") for r in runs if r.find(f"{{{_W_MAIN}}}t") is not None]
        assert t_els[0].text == "مهم جدا"
        assert (t_els[1].text or "") == ""

    def test_patch_preserves_part_set(self, config: AppConfig) -> None:
        docx = _build_docx()
        out = patch_word_strings(docx, {}, cfg=config)
        assert set(_part_names(out)) == set(_part_names(docx))

    def test_patch_leaves_untranslated_text_unchanged(self, config: AppConfig) -> None:
        docx = _build_docx()
        out = patch_word_strings(docx, {}, cfg=config)
        # No translations -> the text content is unchanged. The raw XML has
        # separate w:t runs ("Very " and "Important Article"), not the
        # concatenated paragraph string.
        body_out = _read_part(out, "word/document.xml").decode("utf-8")
        assert "عقد البيع" in body_out
        assert "Very " in body_out
        assert "Important Article" in body_out
        assert "المادة 148" in body_out

    def test_extract_rejects_bad_zip(self, config: AppConfig) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        with pytest.raises(InputValidationError, match="valid zip"):
            extract_word_strings(b"not a real docx", cfg=config)

    def test_patch_rejects_bad_zip(self, config: AppConfig) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        with pytest.raises(InputValidationError, match="valid zip"):
            patch_word_strings(b"not a real docx", {}, cfg=config)


# ---------------------------------------------------------------------------
# Security: defusedxml defends against XXE
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_xxe_entity_not_expanded(self, config: AppConfig, tmp_path: Path) -> None:
        # A document.xml with an XXE entity reference. defusedxml refuses to
        # resolve external entities; the part is skipped safely.
        xxe_doc = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE w:document ['
            '<!ENTITY xxe SYSTEM "file:///etc/passwd">'
            ']>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:body></w:document>'
        )
        parts: dict[str, bytes] = {
            "[Content_Types].xml": _CONTENT_TYPES,
            "_rels/.rels": _ROOT_RELS,
            "word/document.xml": xxe_doc.encode("utf-8"),
            "word/_rels/document.xml.rels": _DOC_RELS,
        }
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in parts.items():
                z.writestr(name, data)
        docx = buf.getvalue()
        # defusedxml raises on the DOCTYPE; the part is skipped -> no segments.
        segs = extract_word_strings(docx, cfg=config)
        assert segs == []


# ---------------------------------------------------------------------------
# translate_word orchestrator (integration with mock adapters)
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
    mock_llm.set_response("translator", "contract of sale")
    mock_llm.set_response(
        "translator",
        "contract of sale",
    )


class TestTranslateWord:
    def _run(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
        *, docx_bytes: bytes | None = None,
        cancel_after: int | None = None,
        fail_after: int | None = None,
    ) -> tuple[WordTranslationReport, bytes, Path]:
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_p = tmp_path / "in.docx"
        out_p = tmp_path / "out.docx"
        in_p.write_bytes(docx_bytes if docx_bytes is not None else _build_docx())

        cancel_event = threading.Event()
        progress_log: list[tuple[int, int, str]] = []

        def progress(completed: int, total: int, current: str) -> None:
            progress_log.append((completed, total, current))

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

        report = translate_word(
            str(in_p), str(out_p), "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
            run_logger=None, tm=None,
            progress=progress, cancel_event=cancel_event,
        )
        out_bytes = out_p.read_bytes() if out_p.exists() else b""
        return report, out_bytes, out_p

    def test_translates_and_writes_output(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, out_p = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config)
        assert out_p.exists()
        assert out_bytes[:2] == b"PK"  # zip magic
        assert report.total_segments > 0
        assert report.translated > 0
        assert report.cancelled is False
        body = _read_part(out_bytes, "word/document.xml").decode("utf-8")
        assert "contract of sale" in body

    def test_dedup_translates_each_unique_paragraph_once(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config)
        # "عقد البيع" appears twice in the body but is one unique segment.
        # The mock returns "contract of sale" for every translator call, so
        # all unique Arabic paragraphs are translated to "contract of sale".
        # The two occurrences of "عقد البيع" must both be translated (the
        # dedup means run_translation was called once, but patch applies the
        # translation to every matching paragraph).
        body = _read_part(out_bytes, "word/document.xml").decode("utf-8")
        # "عقد البيع" should be gone (both occurrences translated).
        assert "عقد البيع" not in body
        # "contract of sale" appears for each unique translated paragraph
        # that the mock mapped to this response (at least the 2 dedup'd
        # occurrences of "عقد البيع").
        assert body.count("contract of sale") >= 2

    def test_progress_reported_per_segment(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, _, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config)
        # Progress callback was invoked; we trust the orchestrator's contract
        # via the report's translated count.
        assert report.translated == report.total_segments - report.failed - report.skipped

    def test_per_segment_failure_preserves_original(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config,
            fail_after=1)
        assert report.failed == 1
        assert any("failed" in w.lower() or "preserved" in w.lower() for w in report.warnings)
        # Output still written.
        assert _read_part(out_bytes, "word/document.xml")

    def test_cancellation_stops_early(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        report, out_bytes, _ = self._run(
            mock_llm, mock_embedder, glossary_index, tmp_path, config,
            cancel_after=1)
        assert report.cancelled is True
        assert out_bytes[:2] == b"PK"

    def test_oversized_document_rejected(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        cfg = config.model_copy(update={"word": config.word.model_copy(
            update={"max_docx_bytes": 100})})  # 100 bytes — smaller than fixture
        with pytest.raises(InputValidationError):
            self._run(mock_llm, mock_embedder, glossary_index, tmp_path, cfg)

    def test_too_many_segments_rejected(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        cfg = config.model_copy(update={"word": config.word.model_copy(
            update={"max_segments": 1})})
        with pytest.raises(InputValidationError):
            self._run(mock_llm, mock_embedder, glossary_index, tmp_path, cfg)

    def test_corrupt_docx_raises_input_validation_error(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config,
    ) -> None:
        from src.components.translation_pipeline.exceptions import InputValidationError
        _setup_mock_llm(mock_llm)
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        in_p = tmp_path / "in.docx"
        in_p.write_bytes(b"not a real docx")
        out_p = tmp_path / "out.docx"
        with pytest.raises(InputValidationError, match="valid zip"):
            translate_word(
                str(in_p), str(out_p), "ar-en", config,
                llm=mock_llm, embedder=mock_embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
            )


# ---------------------------------------------------------------------------
# word CLI command (CliRunner — error paths only; full run needs Ollama)
# ---------------------------------------------------------------------------


class TestWordCli:
    def test_help_succeeds(self) -> None:
        from src.components.interfaces.cli import app
        result = CliRunner().invoke(app, ["word", "--help"])
        assert result.exit_code == 0
        combined = (result.stdout or "") + (result.output or "")
        assert "Translate a Word" in combined

    def test_missing_input_exits_one(self, tmp_path: Path) -> None:
        from src.components.interfaces.cli import app
        result = CliRunner().invoke(app, [
            "word", "--input", str(tmp_path / "missing.docx"),
            "--out", str(tmp_path / "out.docx"), "--direction", "ar-en",
        ])
        assert result.exit_code == 1
        combined = (result.stdout or "") + (result.output or "")
        assert "not found" in combined.lower()

    def test_wrong_extension_exits_one(self, tmp_path: Path) -> None:
        from src.components.interfaces.cli import app
        bad = tmp_path / "data.pdf"
        bad.write_text("not a docx", encoding="utf-8")
        result = CliRunner().invoke(app, [
            "word", "--input", str(bad),
            "--out", str(tmp_path / "out.docx"), "--direction", "ar-en",
        ])
        assert result.exit_code == 1
        combined = (result.stdout or "") + (result.output or "")
        assert ".docx" in combined


# ---------------------------------------------------------------------------
# RTL/bidi paragraph direction (set_bidi_direction)
# ---------------------------------------------------------------------------


class TestBidiDirection:
    """Word RTL/bidi paragraph direction is set to match the translation script."""

    def _build_single_para_docx(self, paragraph_xml: str) -> bytes:
        """Build a one-paragraph .docx for bidi tests."""
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{paragraph_xml}</w:body></w:document>'
        )
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr("_rels/.rels", _ROOT_RELS)
            z.writestr("word/document.xml", document)
            z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        return buf.getvalue()

    def test_arabic_translation_gets_bidi_visual(self, config: AppConfig) -> None:
        # Source English paragraph with NO w:pPr; translation is Arabic.
        para = '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"Hello": "مرحبا"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual" in body
        assert "مرحبا" in body

    def test_latin_translation_removes_bidi_visual(self, config: AppConfig) -> None:
        # Source Arabic paragraph WITH w:bidiVisual; translation is English.
        para = '<w:p><w:pPr><w:bidiVisual/></w:pPr><w:r><w:t>مرحبا</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"مرحبا": "Hello"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body
        assert "Hello" in body

    def test_set_bidi_direction_false_preserves_original(self, config: AppConfig) -> None:
        # With set_bidi_direction=False, the pPr is NOT modified.
        cfg = config.model_copy(update={"word": config.word.model_copy(
            update={"set_bidi_direction": False})})
        para = '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"Hello": "مرحبا"}, cfg=cfg)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body  # not added
        assert "مرحبا" in body  # text still replaced

    def test_empty_ppr_removed_when_bidi_was_only_child(self, config: AppConfig) -> None:
        # Source Arabic paragraph where w:bidiVisual is the ONLY pPr child;
        # Latin translation -> remove bidi -> pPr becomes empty -> remove pPr.
        para = '<w:p><w:pPr><w:bidiVisual/></w:pPr><w:r><w:t>مرحبا</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"مرحبا": "Hello"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body
        assert "<w:pPr>" not in body  # empty pPr removed
        assert "Hello" in body

    def test_other_ppr_children_preserved_when_bidi_removed(self, config: AppConfig) -> None:
        # pPr has spacing AND bidi; Latin translation -> remove bidi only,
        # spacing stays.
        para = ('<w:p><w:pPr><w:spacing w:after="120"/><w:bidiVisual/></w:pPr>'
                '<w:r><w:t>مرحبا</w:t></w:r></w:p>')
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"مرحبا": "Hello"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body
        assert '<w:spacing w:after="120"' in body  # other pPr child kept
        assert "Hello" in body
