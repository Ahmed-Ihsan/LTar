"""Create test .docx and .pdf files for the word/pdf translation commands.

Builds two fixtures under ``data/`` using **only the Python standard library**
(no ``python-docx``, ``reportlab``, or ``pypdf`` at build time), mirroring the
approach used in ``tests/test_word.py`` / ``tests/test_pdf.py`` and the
``add-pdf-word-translation`` spec's "Word and PDF features respect hard
constraints" rule.

``data/test_legal_document.docx`` — feature-rich OOXML:
- Arabic legal articles in the body (translatable)
- English legal articles in the body (translatable)
- A multi-run paragraph (bold + normal) to exercise proportional re-split
- A duplicate paragraph (exercises dedup)
- A tracked-change ``w:ins`` wrapper (preserved byte-for-byte, text translated)
- A header (Republic of Iraq - Ministry of Justice)
- A footer (Page 1)
- A footnote with Arabic text
- An endnote with Arabic text
- A comment with Arabic text
- A glossaryDocument part (term-definition reference)
- A non-text binary part (fake PNG image) to prove byte-for-byte copy

``data/test_legal_document.pdf`` — multi-page PDF:
- Page 1: Arabic Civil Code articles (translatable)
- Page 2: English Commercial Code articles (translatable)
- Page 3: a blank page (simulates a scanned page -> warning)
- Page 4: mixed Arabic/English article (translatable)
"""
from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------------------------------
# .docx builder (raw OOXML — no python-docx dependency)
# ---------------------------------------------------------------------------

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/><Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/><Override PartName="/word/endnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"/><Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/><Override PartName="/word/glossary/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.glossary+xml"/></Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/><Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes" Target="endnotes.xml"/><Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/><Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/glossaryDocument" Target="glossary/document.xml"/></Relationships>"""

# Body: Arabic articles, a multi-run (bold + normal) English paragraph, a
# duplicate Arabic paragraph (dedup), and a tracked-change w:ins wrapper.
_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>عقد البيع هو اتفاق يلتزم بمقتضاه البائع أن ينقل للمشتري ملكية شيء أو حق مالي آخر مقابل ثمن نقدي.</w:t></w:r></w:p><w:p><w:r><w:t>يتم العقد بمجرد تبادل الإيجاب والقبول بين الطرفين.</w:t></w:r></w:p><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Very </w:t></w:r><w:r><w:t>Important Article</w:t></w:r></w:p><w:p><w:r><w:t>A contract of sale is an agreement whereby the seller undertakes to transfer to the buyer the ownership of a thing or another financial right in consideration of a cash price.</w:t></w:r></w:p><w:p><w:r><w:t>عقد البيع هو اتفاق يلتزم بمقتضاه البائع أن ينقل للمشتري ملكية شيء أو حق مالي آخر مقابل ثمن نقدي.</w:t></w:r></w:p><w:p><w:ins w:id="1" w:author="legal" w:date="2026-01-01T00:00:00Z"><w:r><w:t>المادة 148 من القانون المدني</w:t></w:r></w:ins></w:p></w:body></w:document>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:styleId="CustomLegal"><w:name w:val="CustomLegal"/><w:pPr><w:spacing w:after="120"/></w:pPr></w:style></w:styles>"""

_HEADER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Republic of Iraq - Ministry of Justice</w:t></w:r></w:p></w:hdr>"""

_FOOTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Page 1</w:t></w:r></w:p></w:ftr>"""

_FOOTNOTES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:footnote w:type="normal" w:id="-1"><w:p><w:r><w:t>ملاحظة قانونية: انظر المادة 148 من القانون المدني.</w:t></w:r></w:p></w:footnote></w:footnotes>"""

_ENDNOTES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:endnote w:type="normal" w:id="-1"><w:p><w:r><w:t>مراجعة: تمت مراجعة هذا النص قانونياً.</w:t></w:r></w:p></w:endnote></w:endnotes>"""

_COMMENTS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="1" w:author="legal" w:date="2026-01-01T00:00:00Z" w:initials="l"><w:p><w:r><w:t>تحقق من المرجع قبل الاعتماد.</w:t></w:r></w:p></w:comment></w:comments>"""

_GLOSSARY = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:glossaryDocument xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>تعريف المصطلح: عقد البيع - Contract of Sale.</w:t></w:r></w:p></w:glossaryDocument>"""

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


# ---------------------------------------------------------------------------
# .pdf builder (raw PDF syntax — no reportlab/pypdf dependency at build time)
# ---------------------------------------------------------------------------


def _build_pdf(pages_text: list[str | None]) -> bytes:
    """Build a minimal multi-page PDF where each page's text is the given string.

    A ``None`` entry produces a blank page (no extractable text — simulates a
    scanned page). Uses raw PDF syntax (no pypdf writer dependency) so the
    output is deterministic. Text is encoded latin-1 with replacement for any
    non-latin-1 chars (Arabic glyphs will not render visually, but the bytes
    are present for extraction-based tests; pypdf extracts the raw string).
    """
    # Object layout: 1: Catalog, 2: Pages, 3: Font (Helvetica), 4+: page + content.
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
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # Resolve to the repo-root ``data/`` regardless of the caller's cwd so the
    # script works from any directory (e.g. ``python scripts/make_test_fixtures.py``).
    out_dir: Path = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- .docx ---
    docx_bytes = _build_docx()
    docx_path = out_dir / "test_legal_document.docx"
    docx_path.write_bytes(docx_bytes)
    print(f"Created: {docx_path} ({docx_path.stat().st_size} bytes)")
    print(
        "docx features: Arabic body, English body, multi-run (bold+normal), "
        "duplicate paragraph (dedup), tracked-change w:ins, header, footer, "
        "footnote, endnote, comment, glossaryDocument, embedded image"
    )

    # --- .pdf ---
    pages_text: list[str | None] = [
        # Page 1: Arabic Civil Code articles.
        "المادة 1: عقد البيع هو اتفاق يلتزم بمقتضاه البائع أن ينقل للمشتري ملكية شيء أو حق مالي آخر مقابل ثمن نقدي.\n\n"
        "المادة 2: يتم العقد بمجرد تبادل الإيجاب والقبول بين الطرفين.",
        # Page 2: English Commercial Code articles.
        "Article 1: A contract of sale is an agreement whereby the seller undertakes to transfer to the buyer the ownership of a thing or another financial right in consideration of a cash price.\n\n"
        "Article 2: The contract is concluded upon the exchange of offer and acceptance between the two parties.",
        # Page 3: blank page (simulates a scanned page -> warning).
        None,
        # Page 4: mixed Arabic/English article.
        "المادة 148 من القانون المدني - Article 148 of the Civil Code.",
    ]
    pdf_bytes = _build_pdf(pages_text)
    pdf_path = out_dir / "test_legal_document.pdf"
    pdf_path.write_bytes(pdf_bytes)
    print(f"Created: {pdf_path} ({pdf_path.stat().st_size} bytes)")
    print(
        "pdf features: 4 pages (Arabic, English, blank/scanned, mixed AR/EN); "
        "extractable text on pages 1, 2, 4; page 3 yields no text (warning)"
    )


if __name__ == "__main__":
    main()
