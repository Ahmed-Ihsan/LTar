"""Pydantic configuration models for the Iraqi Legal Translation Agent.

Holds the sub-models (``PathsConfig``, ``ChromaConfig``) used by
:class:`src.config.config.AppConfig`. Splitting the models into their own
module keeps :mod:`src.config.config` focused on loading/validation logic.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


class PathsConfig(BaseModel):
    """Filesystem paths, all relative to the project root."""

    data_dir: str = "data"
    corpus_dir: str = "data/corpus"
    glossary_dir: str = "data/glossary"
    raw_dir: str = "data/raw"
    db_dir: str = "db"
    glossary_db: str = "db/glossary.sqlite"
    chroma_dir: str = "db/chroma"

    @field_validator("data_dir", "corpus_dir", "glossary_dir", "raw_dir",
                     "db_dir", "glossary_db", "chroma_dir")
    @classmethod
    def _non_empty_path(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("path must not be empty or whitespace-only")
        return v


class ChromaConfig(BaseModel):
    """ChromaDB HNSW index tuning for a small corpus on low-RAM hardware."""

    space: str = "cosine"
    hnsw_M: int = 8
    construction_ef: int = 64
    search_ef: int = 32

    @field_validator("hnsw_M")
    @classmethod
    def _hnsw_m_min(cls, v: int) -> int:
        if v < 2:
            raise ValueError(f"hnsw_M must be >= 2, got {v}")
        return v

    @field_validator("construction_ef", "search_ef")
    @classmethod
    def _ef_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"ef must be >= 1, got {v}")
        return v


class ExcelConfig(BaseModel):
    """Excel (.xlsx) translation feature toggles and limits.

    Controls which human-readable text locations the Excel adapter translates,
    and the per-segment size cap. Defaults translate every supported location
    so a plain ``excel`` run translates the whole workbook.
    """

    translate_comments: bool = True
    translate_headers_footers: bool = True
    translate_chart_titles: bool = True
    max_segment_chars: int = 4096
    max_xlsx_bytes: int = 100 * 1024 * 1024
    max_segments: int = 10000

    @field_validator("max_segment_chars")
    @classmethod
    def _max_segment_chars_min(cls, v: int) -> int:
        if v < 16:
            raise ValueError(f"max_segment_chars must be >= 16, got {v}")
        return v

    @field_validator("max_xlsx_bytes")
    @classmethod
    def _max_xlsx_bytes_min(cls, v: int) -> int:
        if v < 1_048_576:
            raise ValueError(f"max_xlsx_bytes must be >= 1 MiB, got {v}")
        return v

    @field_validator("max_segments")
    @classmethod
    def _max_segments_min(cls, v: int) -> int:
        if v < 100:
            raise ValueError(f"max_segments must be >= 100, got {v}")
        return v


class UiConfig(BaseModel):
    """UI backend selection (web vs Tkinter).

    ``backend`` selects which desktop UI to launch via ``iraqi-translate ui``.
    """

    backend: Literal["web", "tk"] = "web"


class WordConfig(BaseModel):
    """Word (.docx) translation feature toggles and limits.

    Controls which human-readable text locations the Word adapter translates,
    and the per-segment / per-document size caps. Defaults translate every
    supported location so a plain ``word`` run translates the whole document
    body, comments, headers/footers, footnotes, and endnotes. The
    ``glossaryDocument`` part is OFF by default (it is a term-definition
    reference, not translatable content).
    """

    translate_comments: bool = True
    translate_headers_footers: bool = True
    translate_footnotes: bool = True
    translate_endnotes: bool = True
    translate_glossary_doc: bool = False
    max_segment_chars: int = 8192
    max_docx_bytes: int = 50 * 1024 * 1024
    max_segments: int = 20000

    @field_validator("max_segment_chars")
    @classmethod
    def _max_segment_chars_min(cls, v: int) -> int:
        if v < 16:
            raise ValueError(f"max_segment_chars must be >= 16, got {v}")
        return v

    @field_validator("max_docx_bytes")
    @classmethod
    def _max_docx_bytes_min(cls, v: int) -> int:
        if v < 1_048_576:
            raise ValueError(f"max_docx_bytes must be >= 1 MiB, got {v}")
        return v

    @field_validator("max_segments")
    @classmethod
    def _max_segments_min(cls, v: int) -> int:
        if v < 100:
            raise ValueError(f"max_segments must be >= 100, got {v}")
        return v


class PdfConfig(BaseModel):
    """PDF (.pdf) translation feature toggles and limits.

    The PDF adapter extracts text per page and writes a translated sidecar
    file (``.docx`` by default, or ``.txt``). ``skip_header_footer`` drops
    page-header / page-footer lines that ``pypdf`` emits inline with the body
    text on each page (a common artifact of PDF text extraction).
    """

    out_format: Literal["docx", "txt"] = "docx"
    max_pdf_bytes: int = 100 * 1024 * 1024
    max_pages: int = 500
    max_segment_chars: int = 8192
    max_segments: int = 20000
    skip_header_footer: bool = True

    @field_validator("max_pdf_bytes")
    @classmethod
    def _max_pdf_bytes_min(cls, v: int) -> int:
        if v < 1_048_576:
            raise ValueError(f"max_pdf_bytes must be >= 1 MiB, got {v}")
        return v

    @field_validator("max_pages")
    @classmethod
    def _max_pages_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"max_pages must be >= 1, got {v}")
        return v

    @field_validator("max_segment_chars")
    @classmethod
    def _max_segment_chars_min(cls, v: int) -> int:
        if v < 16:
            raise ValueError(f"max_segment_chars must be >= 16, got {v}")
        return v

    @field_validator("max_segments")
    @classmethod
    def _max_segments_min(cls, v: int) -> int:
        if v < 100:
            raise ValueError(f"max_segments must be >= 100, got {v}")
        return v
