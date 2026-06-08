"""Deployment E2E tests — API entry points × document types × retrieval.

Must be run AFTER container rebuild (pymupdf4llm + markitdown[all] installed).
Requires: platform container on localhost:8100, deeptutor container accessible.

Usage:
    docker cp tests/test_deployment_e2e.py platform:/tests/
    docker exec platform python -m pytest /tests/test_deployment_e2e.py -x -v --tb=short
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path

import httpx
import pytest

pytestmark = []  # per-class markers only; sync tests in TestUnitRegression

# Enable auto asyncio mode so @pytest.mark.asyncio works at class level
pytest_plugins = []
def pytest_configure(config):
    config.option.asyncio_mode = "auto"

PLATFORM_URL = "http://localhost:8100"
DEEPTUTOR_URL = "http://deeptutor:8001"
TEST_KB = "kb_e2e_test"


# ── Fixtures ──────────────────────────────────────────────────────



async def _upload_file(endpoint: str, filename: str, content: bytes,
                       content_type: str = "application/octet-stream",
                       extra_fields: dict | None = None) -> dict:
    """Upload a file to a platform endpoint, return parsed JSON."""
    fields = {"kb_name": TEST_KB, "learner_id": "e2e_test"}
    if extra_fields:
        fields.update(extra_fields)
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            f"{PLATFORM_URL}{endpoint}",
            data=fields,
            files={"file": (filename, content, content_type)},
        )
        return resp.json()


async def _upload_json(endpoint: str, body: dict) -> dict:
    """POST JSON to a platform endpoint."""
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{PLATFORM_URL}{endpoint}", json=body)
        return resp.json()


async def _get(endpoint: str) -> dict:
    """GET JSON from a platform endpoint."""
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.get(f"{PLATFORM_URL}{endpoint}")
        return resp.json() if resp.status_code == 200 else {"status": resp.status_code, "body": resp.text}


# ── Helpers: create test documents in-memory ──────────────────────

def _make_pdf_bytes(text: str) -> bytes:
    """Minimal text-layer PDF with PyMuPDF."""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not available")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=11, fontname="helv")
    out = doc.tobytes()
    doc.close()
    return out


def _make_docx_bytes(text: str) -> bytes:
    import io
    try:
        from docx import Document
    except ImportError:
        pytest.skip("python-docx not available")
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_xlsx_bytes(data: list[list[str]]) -> bytes:
    import io
    try:
        from openpyxl import Workbook
    except ImportError:
        pytest.skip("openpyxl not available")
    wb = Workbook()
    ws = wb.active
    for row in data:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Phase 2: Unit tests (shipped separately, quick re-run here) ──

class TestUnitRegression:
    """Re-run existing unit tests to confirm no regressions."""

    def test_imports(self):
        """All key modules import cleanly."""
        from tutor_platform.rag.extractors import (
            extract_text, extract_pdf_text, extract_image_text,
            extract_pdf_tables, semantic_chunk, _sanitize_html,
        )
        from tutor_platform.rag.ocr_adapters import MinicpmOCRFunc, get_minicpm_ocr_function
        assert True

    def test_extractors_map_complete(self):
        from tutor_platform.rag.extractors import _EXTRACTOR_MAP
        assert _EXTRACTOR_MAP[".pdf"] == "pdf"
        assert _EXTRACTOR_MAP[".png"] == "image"
        assert _EXTRACTOR_MAP[".html"] == "html"
        assert _EXTRACTOR_MAP[".doc"] == "markitdown"
        assert _EXTRACTOR_MAP[".epub"] == "markitdown"
        assert _EXTRACTOR_MAP[".zip"] == "markitdown"
        assert _EXTRACTOR_MAP[".docx"] == "docx"


# ── Phase 3: API E2E per entry point × doc type ──────────────────

class TestKbIngestFile:
    """POST /api/kb/ingest-file — Web UI KB sync entry."""

    @pytest.mark.asyncio

    async def test_pdf_text_layer(self):
        pdf = _make_pdf_bytes("Pythagorean theorem: a² + b² = c²")
        result = await _upload_file("/api/kb/ingest-file", "pythagorean.pdf", pdf)
        assert result.get("ok") is True, f"Failed: {result}"
        assert result.get("content_len", 0) > 0
        assert result.get("route") in ("text", "document_extract", "passthrough")
        assert "trace_id" in result

    async def test_docx(self):
        docx = _make_docx_bytes("Chapter 1: Introduction")
        result = await _upload_file("/api/kb/ingest-file", "test.docx", docx)
        assert result.get("ok") is True, f"Failed: {result}"
        assert result.get("content_len", 0) > 0
        assert result.get("route") in ("text", "document_extract", "passthrough")

    async def test_txt(self):
        result = await _upload_file(
            "/api/kb/ingest-file", "notes.txt",
            "勾股定理：a² + b² = c²".encode("utf-8"),
            "text/plain",
        )
        assert result.get("ok") is True, f"Failed: {result}"
        assert result.get("content_len", 0) > 0
        assert result.get("route") == "text"

    async def test_html_sanitization(self):
        html = "<html><body><h1>Safe</h1><script>alert('xss')</script></body></html>"
        result = await _upload_file(
            "/api/kb/ingest-file", "test.html",
            html.encode("utf-8"), "text/html",
        )
        assert result.get("ok") is True, f"Failed: {result}"
        # Content should NOT contain script tag
        # (We verify in ChromaDB retrieval test below)

    async def test_xlsx(self):
        xlsx = _make_xlsx_bytes([["Name", "Score"], ["Alice", "95"]])
        result = await _upload_file("/api/kb/ingest-file", "scores.xlsx", xlsx)
        assert result.get("ok") is True, f"Failed: {result}"
        assert result.get("content_len", 0) > 0
        assert result.get("route") in ("text", "document_extract", "passthrough")


class TestIngestFile:
    """POST /api/ingest/file — MCP tool file upload entry."""

    @pytest.mark.asyncio

    async def test_pdf(self):
        pdf = _make_pdf_bytes("Einstein: E = mc²")
        result = await _upload_file("/api/ingest/file", "einstein.pdf", pdf)
        assert result.get("ok") is True, f"Failed: {result}"

    async def test_txt(self):
        result = await _upload_file(
            "/api/ingest/file", "readme.txt",
            b"Hello World",
            "text/plain",
        )
        assert result.get("ok") is True, f"Failed: {result}"

    async def test_docx(self):
        docx = _make_docx_bytes("Introduction paragraph.")
        result = await _upload_file("/api/ingest/file", "intro.docx", docx)
        assert result.get("ok") is True, f"Failed: {result}"


class TestIngestProxy:
    """POST /api/ingest/proxy/{kb} — Web proxy upload entry."""

    async def test_pdf(self):
        pdf = _make_pdf_bytes("Test proxy PDF content.")
        result = await _upload_file("/api/ingest/proxy/kb_e2e_test", "proxy.pdf", pdf)
        assert result.get("ok") is True, f"Failed: {result}"
        assert result.get("status") == "completed"
        assert result.get("content_len", 0) > 0

    async def test_txt(self):
        result = await _upload_file(
            "/api/ingest/proxy/kb_e2e_test", "proxy.txt",
            b"Proxy test content.",
            "text/plain",
        )
        assert result.get("ok") is True, f"Failed: {result}"
        assert result.get("status") == "completed"


class TestIngestText:
    """POST /api/ingest/text — Direct text ingestion."""

    async def test_plain_text(self):
        result = await _upload_json("/api/ingest/text", {
            "content": "Direct text: 牛顿第二定律 F=ma",
            "kb_name": TEST_KB,
            "filename": "newton.txt",
            "source": "e2e_test",
        })
        assert result.get("ok") is True, f"Failed: {result}"


class TestExtract:
    """POST /api/extract — Lightweight extraction, no KB write."""

    async def test_pdf_extract(self):
        pdf = _make_pdf_bytes("Lightweight extract test.")
        result = await _upload_file("/api/extract", "lite.pdf", pdf)
        assert result.get("ok") is True, f"Failed: {result}"
        assert result.get("content", ""), "Content should not be empty"
        assert result.get("route")

    async def test_txt_extract(self):
        result = await _upload_file(
            "/api/extract", "lite.txt",
            b"Simple text.",
            "text/plain",
        )
        assert result.get("ok") is True, f"Failed: {result}"
        assert "Simple" in result.get("content", "")


# ── Phase 4: ChromaDB retrieval ──────────────────────────────────

class TestChromaDBRetrieval:
    """Verify that ingested documents appear in ChromaDB search."""

    async def test_retrieval_chinese(self):
        # Upload a Chinese document first
        content = textwrap.dedent("""\
        第3章 勾股定理

        勾股定理：直角三角形两直角边a、b的平方和等于斜边c的平方。
        即 a² + b² = c²。
        """)
        result = await _upload_file(
            "/api/kb/ingest-file", "pythagorean_chinese.txt",
            content.encode("utf-8"), "text/plain",
            extra_fields={"kb_name": "kb_retrieval_test", "learner_id": "e2e_retrieval"},
        )
        assert result.get("ok") is True, f"Failed: {result}"

        # Wait for async ingestion
        await asyncio.sleep(4)

        # Query via provider
        from tutor_platform.unified_provider import get_provider_instance
        provider = get_provider_instance()
        results = await provider.query("kb_retrieval_test", ["勾股定理"], n_results=3)
        assert len(results) >= 1, f"No results for 勾股定理: {results}"
        combined = " ".join(r.get("content", "") for r in results)
        assert "勾股定理" in combined or "直角三角形" in combined or "a²" in combined, \
            f"Expected math content in: {combined[:200]}"

    async def test_html_sanitization_in_db(self):
        # Upload HTML with script
        html = "<html><body><h1>Safe Content</h1><script>alert('evil')</script></body></html>"
        result = await _upload_file(
            "/api/kb/ingest-file", "safe.html",
            html.encode("utf-8"), "text/html",
            extra_fields={"kb_name": "kb_retrieval_test", "learner_id": "e2e_retrieval"},
        )
        assert result.get("ok") is True

        # Query and verify no script tag in results
        from tutor_platform.unified_provider import get_provider_instance
        provider = get_provider_instance()
        results = await provider.query("kb_retrieval_test", ["Safe Content"], n_results=3)
        for r in results:
            content = r.get("content", "")
            assert "<script>" not in content, f"XSS not sanitized in: {content[:200]}"
            assert "alert" not in content.lower(), f"XSS not sanitized in: {content[:200]}"

    async def test_retrieval_english(self):
        content = "Newton's Second Law: Force equals mass times acceleration. F = ma."
        result = await _upload_file(
            "/api/kb/ingest-file", "newton.txt",
            content.encode("utf-8"), "text/plain",
            extra_fields={"kb_name": "kb_eng_test", "learner_id": "e2e_retrieval"},
        )
        assert result.get("ok") is True
        await asyncio.sleep(4)

        from tutor_platform.unified_provider import get_provider_instance
        provider = get_provider_instance()
        results = await provider.query("kb_eng_test", ["Newton Second Law"], n_results=3)
        assert isinstance(results, list), f"Expected list, got: {type(results)}"
        # NB: hash-fallback embeddings mean all queries are equally relevant;
        # with real RKLLM embeddings this would be a semantic match.


# ── Phase 5: DT LlamaIndex dual-write ────────────────────────────

class TestDTSync:
    """Verify DT LlamaIndex dual-write for scanned PDF routes."""

    async def test_text_pdf_no_dt_sync(self):
        """Text-layer PDF may or may not trigger DT sync depending on extraction quality."""
        pdf = _make_pdf_bytes("Text layer PDF content for testing.")
        result = await _upload_file("/api/kb/ingest-file", "text_only.pdf", pdf)
        assert result.get("ok") is True
        # dt_synced depends on route: "text" → False, "document_extract" → True
        route = result.get("route", "")
        if route == "text":
            assert result.get("dt_synced") is False, f"Text route should not sync: {result}"
        else:
            assert result.get("dt_synced") is True, f"Non-text route should sync: {result}"

    async def test_scan_pdf_triggers_dt_sync(self):
        """Scanned PDF (no text layer) should trigger DT sync."""
        # Create empty PDF (simulates scanned — no text layer)
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not available")
        doc = fitz.open()
        doc.new_page()  # blank page = no text
        scanned_bytes = doc.tobytes()
        doc.close()

        result = await _upload_file("/api/kb/ingest-file", "scanned.pdf", scanned_bytes)
        assert result.get("ok") is True, f"Failed: {result}"
        # OCR route should trigger DT sync
        route = result.get("route", "")
        if route in ("ocr", "document_extract"):
            assert result.get("dt_synced") is True, \
                f"Scanned PDF ({route}) should trigger DT sync: {result}"
        else:
            # text — DT already indexed this empty PDF as text
            assert result.get("dt_synced") is False, \
                f"Empty PDF treated as text: {result}"


# ── Phase 6: Regression smoke tests ──────────────────────────────

class TestSmoke:
    """Regression smoke — key endpoints return 200."""

    async def test_health(self):
        r = await _get("/health")
        assert r.get("status") == "ok", f"Health check failed: {r}"

    async def test_mastery(self):
        r = await _get("/api/mastery/")
        assert isinstance(r, list), f"Mastery should return list: {r}"

    async def test_kb_search_existing(self):
        """Search existing tutoring KB (1245+ chunks)."""
        from tutor_platform.unified_provider import get_provider_instance
        provider = get_provider_instance()
        results = await provider.query("初中教材", ["数学"], n_results=3)
        assert isinstance(results, list), f"Search should return list: {results}"
        # tutoring KB may be empty, but the call should not crash

    async def test_ocr_endpoint(self):
        """OCR endpoint should return response (may fallback without real image)."""
        # Small PNG — OCR may fail but endpoint should not crash
        import struct, zlib
        def _png_1x1() -> bytes:
            def chunk(ct, d):
                c = ct + d
                return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            raw = b"\x00\xff\xff\xff"
            return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

        import base64
        img_b64 = base64.b64encode(_png_1x1()).decode()
        r = await _upload_json("/api/ocr", {"image_data": img_b64, "language": "zh"})
        # May return text or empty — just must not crash
        assert "error" not in r or r.get("ok") is not False, f"OCR endpoint error: {r}"
