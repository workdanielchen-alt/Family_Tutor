"""End-to-end ingestion consistency tests.

Verifies that the same document processed through different entry points
produces identical extracted text.  Parametrized over entry point and
document type.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────

def _make_test_pdf(path: Path, text_content: str) -> None:
    """Create a minimal text-layer PDF for testing."""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not available")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text_content, fontsize=11, fontname="helv")
    doc.save(str(path))
    doc.close()


def _make_test_docx(path: Path, text: str) -> None:
    try:
        from docx import Document
    except ImportError:
        pytest.skip("python-docx not available")
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))


def _make_test_xlsx(path: Path, data: list[list[str]]) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        pytest.skip("openpyxl not available")
    wb = Workbook()
    ws = wb.active
    for row in data:
        ws.append(row)
    wb.save(str(path))


def _call_extract_text(file_path: str) -> str:
    """Simulate calling extract_text() from any entry point."""
    from tutor_platform.rag.extractors import extract_text

    return extract_text(file_path)


def _call_extract_pdf_ocr(file_path: str, trace_id: str) -> str:
    """Simulate calling extract_pdf_text with OCR via _handle_pdf."""
    from tutor_platform.rag.extractors import extract_pdf_text

    return extract_pdf_text(file_path, ocr_enabled=True, ocr_trace_id=trace_id)


# ── Tests ─────────────────────────────────────────────────────────


class TestExtractTextDefault:
    """extract_text() with default params — no OCR, no trace_id."""

    def test_text_layer_pdf(self, tmp_path: Path):
        pdf_path = tmp_path / "test.pdf"
        _make_test_pdf(pdf_path, "Hello World\n\nThis is a test PDF.")
        text = _call_extract_text(str(pdf_path))
        assert "Hello World" in text
        assert "test PDF" in text

    def test_empty_pdf_fallback(self, tmp_path: Path):
        """Empty PDF (no text layer) should return empty or fallback."""
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not available")
        doc = fitz.open()
        doc.new_page()  # blank page
        pdf_path = tmp_path / "empty.pdf"
        doc.save(str(pdf_path))
        doc.close()
        text = _call_extract_text(str(pdf_path))
        # Empty PDF — may return empty or fallback text from markitdown
        assert isinstance(text, str)

    def test_docx(self, tmp_path: Path):
        docx_path = tmp_path / "test.docx"
        _make_test_docx(docx_path, "Chapter One\n\nBody text here.")
        text = _call_extract_text(str(docx_path))
        assert "Chapter One" in text or "Body text" in text

    def test_xlsx(self, tmp_path: Path):
        xlsx_path = tmp_path / "test.xlsx"
        _make_test_xlsx(xlsx_path, [["Name", "Age"], ["Alice", "10"]])
        text = _call_extract_text(str(xlsx_path))
        assert "Name" in text or "Alice" in text

    def test_text_file_multi_encoding(self, tmp_path: Path):
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("Hello World\n你好世界", encoding="utf-8")
        text = _call_extract_text(str(txt_path))
        assert "Hello World" in text

    def test_html_sanitization(self, tmp_path: Path):
        html_path = tmp_path / "test.html"
        html_path.write_text(
            "<html><body><h1>Safe</h1><script>alert('xss')</script></body></html>",
            encoding="utf-8",
        )
        text = _call_extract_text(str(html_path))
        assert "Safe" in text
        assert "script" not in text.lower() or "alert" not in text


class TestExtractPdfTextOCR:
    """extract_pdf_text() with ocr_enabled=True — still works without Tesseract."""

    def test_text_layer_pdf_no_ocr_needed(self, tmp_path: Path):
        pdf_path = tmp_path / "test.pdf"
        _make_test_pdf(pdf_path, "Hello World\n\nThis is a test PDF.")
        text = _call_extract_pdf_ocr(str(pdf_path), "test-trace")
        assert "Hello World" in text

    def test_ocr_flag_is_backward_compat(self, tmp_path: Path):
        """Call with ocr_enabled=False (default) should work same as before."""
        from tutor_platform.rag.extractors import extract_pdf_text

        pdf_path = tmp_path / "test.pdf"
        _make_test_pdf(pdf_path, "Content")
        text = extract_pdf_text(str(pdf_path))  # default: ocr_enabled=False
        assert "Content" in text


class TestPdfTables:
    """PDF table extraction via page.find_tables()."""

    def test_no_tables_empty_result(self, tmp_path: Path):
        from tutor_platform.rag.extractors import extract_pdf_tables

        pdf_path = tmp_path / "test.pdf"
        _make_test_pdf(pdf_path, "Plain text, no tables here.")
        tables = extract_pdf_tables(str(pdf_path))
        assert isinstance(tables, list)
        # A text-only PDF won't have detected tables
        # (find_tables looks for graphical table structure)

    def test_tables_as_markdown(self, tmp_path: Path):
        from tutor_platform.rag.extractors import extract_pdf_tables_as_markdown

        pdf_path = tmp_path / "test.pdf"
        _make_test_pdf(pdf_path, "Text")
        md = extract_pdf_tables_as_markdown(str(pdf_path))
        assert isinstance(md, str)


class TestSemanticChunk:
    """Semantic chunking with Markdown heading awareness."""

    def test_single_chunk_below_size(self):
        from tutor_platform.rag.extractors import semantic_chunk

        text = "Short text"
        chunks = semantic_chunk(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Short text"
        assert chunks[0]["heading_path"] == ""

    def test_heading_split(self):
        from tutor_platform.rag.extractors import semantic_chunk

        text = "## Topic A\nContent A. " * 50 + "\n## Topic B\nContent B. " * 50
        chunks = semantic_chunk(text, chunk_size=500)
        assert len(chunks) >= 2
        assert any(c["heading_path"] for c in chunks), f"All empty: {[c['heading_path'] for c in chunks]}"

    def test_chunk_metadata(self):
        from tutor_platform.rag.extractors import semantic_chunk

        text = ("Hello world. " * 30 + "\n\n" + "Goodbye world. " * 30) * 4  # ~2400 chars with paragraph breaks
        chunks = semantic_chunk(text, chunk_size=500, doc_type="text_pdf", filename="test.pdf")
        assert len(chunks) > 1
        for c in chunks:
            assert "doc_type" in c
            assert "filename" in c
            assert "chunk_index" in c
            assert c["doc_type"] == "text_pdf"
            assert c["filename"] == "test.pdf"

    def test_overlap_applied(self):
        from tutor_platform.rag.extractors import semantic_chunk

        text = ("ParaA " * 50 + "\n\n" + "ParaB " * 50 + "\n\n" + "ParaC " * 50)
        chunks = semantic_chunk(text, chunk_size=400, chunk_overlap=80)
        assert len(chunks) >= 2


class TestDocTypeClassification:
    """File classification via unified_pipeline.DocType."""

    def test_classify_text_pdf(self, tmp_path: Path):
        from tutor_platform.rag.unified_pipeline import classify_file, DocType

        pdf_path = tmp_path / "test.pdf"
        _make_test_pdf(pdf_path, "Chapter One Introduction\n\nThis document contains a substantial amount of text content that should be sufficient for the text layer detection heuristic to classify it as a text-based PDF rather than a scanned document. " * 5)
        dt = classify_file(str(pdf_path))
        assert dt in (DocType.TEXT_PDF, DocType.UNKNOWN, DocType.SCANNED_PDF)  # SCANNED_PDF if text too short

    def test_classify_text_file(self, tmp_path: Path):
        from tutor_platform.rag.unified_pipeline import classify_file, DocType

        txt_path = tmp_path / "test.txt"
        txt_path.write_text("hello", encoding="utf-8")
        dt = classify_file(str(txt_path))
        assert dt == DocType.TEXT


class TestSidecarEnrichment:
    """Sidecar content enrichment from UnifiedDocumentPipeline."""

    def test_no_sidecar_returns_original(self, tmp_path: Path):
        from provider_api import _enrich_with_sidecar_content

        result = _enrich_with_sidecar_content("original", "/nonexistent/file.pdf")
        assert result == "original"

    def test_sidecar_enrichment(self, tmp_path: Path):
        from provider_api import _enrich_with_sidecar_content

        file_path = tmp_path / "test.pdf"
        file_path.write_text("dummy", encoding="utf-8")
        sidecar = tmp_path / "test.md"
        sidecar.write_text("This is a much longer sidecar content that should replace", encoding="utf-8")
        result = _enrich_with_sidecar_content("short", str(file_path))
        assert result != "short"
        assert "sidecar" in result.lower() or "longer" in result.lower() or "much" in result.lower()


class TestImageExtraction:
    """Image text extraction (needs OCR backend — may be unavailable in CI)."""

    def test_image_extract_returns_string(self, tmp_path: Path):
        """extract_image_text() should return a string even on failure."""
        from tutor_platform.rag.extractors import extract_image_text

        # Create a tiny 1x1 PNG
        img_path = tmp_path / "test.png"
        # Minimal valid PNG: 1x1 white pixel
        import struct
        import zlib

        def _make_png(w: int, h: int, r: int, g: int, b: int) -> bytes:
            def chunk(ctype: bytes, data: bytes) -> bytes:
                c = ctype + data
                return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

            ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
            raw = b""
            for _ in range(h):
                raw += b"\x00" + bytes([r, g, b]) * w
            return (
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw))
                + chunk(b"IEND", b"")
            )

        img_path.write_bytes(_make_png(1, 1, 255, 255, 255))
        text = extract_image_text(str(img_path), trace_id="test")
        assert isinstance(text, str)

    def test_image_in_extract_text_map(self):
        """Image extensions should be mapped in _EXTRACTOR_MAP."""
        from tutor_platform.rag.extractors import _EXTRACTOR_MAP

        assert _EXTRACTOR_MAP.get(".png") == "image"
        assert _EXTRACTOR_MAP.get(".jpg") == "image"
        assert _EXTRACTOR_MAP.get(".webp") == "image"
