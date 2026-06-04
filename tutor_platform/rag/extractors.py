"""Unified document extractors — single source of truth for text extraction.

Every ingestion path (Web KB upload, WeChat, MCP tools, CLI, chat attachments,
API calls, LlamaIndex document loader) calls these functions so behaviour is
consistent regardless of entry point.

Principles:
  * pymupdf4llm for all PDFs (text layer, scanned, mixed, exams) — one import.
  * python-docx / openpyxl / python-pptx for modern Office — rich structured output.
  * markitdown for EPUB / audio / YouTube / old Office fallback — wide format support.
  * FileTypeRouter for plain text / source code — multi-encoding chain.
  * No Tesseract — OCR is handled by LLM (MiniCPM / rkllama) downstream when needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


# ── PDF extraction ────────────────────────────────────────────────

def extract_pdf_text(
    file_path: str | Path,
    *,
    ocr_enabled: bool = False,
    ocr_trace_id: str = "",
) -> str:
    """Extract text from any PDF as structured Markdown.

    Uses pymupdf4llm.to_markdown() which provides:
      - # heading hierarchy from font-size analysis
      - **bold** / *italic* inline formatting
      - GFM pipe tables from detected table regions
      - Natural reading-order reconstruction for multi-column pages
      - Auto-detected and excluded page headers / footers
      - Embedded image references (![alt](path))

    When ``ocr_enabled=True``, pymupdf4llm's hybrid OCR pipeline is activated:
    only pages/regions without a text layer are OCR'd via the configured
    OCR backend (MiniCPM-V / rkllama via ``ocr_adapters.py``).  Text-layer
    pages pass through unchanged.  No Tesseract required.

    Falls back to raw pymupdf page.get_text() when pymupdf4llm is unavailable
    or raises an exception.
    """
    path = Path(file_path)

    try:
        import pymupdf4llm

        kwargs: dict = {}
        if ocr_enabled:
            from tutor_platform.rag.ocr_adapters import get_minicpm_ocr_function

            kwargs["use_ocr"] = True
            kwargs["ocr_function"] = get_minicpm_ocr_function(trace_id=ocr_trace_id)
            # pymupdf4llm's auto-detection may skip pages with no text-like features.
            # When the caller explicitly enabled OCR (e.g. scanned PDF with empty
            # text layer), force OCR on all pages so MiniCPM-V processes every page.
            kwargs["force_ocr"] = True
        else:
            kwargs["use_ocr"] = False

        md = pymupdf4llm.to_markdown(path, **kwargs)
        if md and len(md.strip()) > 0:
            logger.debug(
                "pymupdf4llm extracted %d chars from %s (ocr=%s)",
                len(md), path.name, ocr_enabled,
            )
            return md
    except ImportError:
        logger.warning("pymupdf4llm not installed, falling back to pymupdf raw text")
    except Exception as exc:
        logger.warning(
            "pymupdf4llm.to_markdown failed for %s: %s — falling back to pymupdf raw text",
            path.name, exc,
        )

    # Fallback: raw pymupdf page-by-page extraction
    return _extract_pdf_text_fast(path)


def extract_pdf_json(file_path: str | Path) -> list[dict]:
    """Extract structured layout data from a PDF via pymupdf4llm.to_json().

    Returns a list of page dicts with bounding-box, layout type, font metadata
    per element.  Used as input for PaperLayoutEngine downstream.
    """
    path = Path(file_path)

    try:
        import pymupdf4llm
        data = pymupdf4llm.to_json(path, use_ocr=False)
        if data:
            return data
    except ImportError:
        logger.warning("pymupdf4llm not installed, falling back to raw pymupdf")
    except Exception as exc:
        logger.warning("pymupdf4llm.to_json failed for %s: %s", path.name, exc)

    return []


def has_pdf_text_layer(file_path: str | Path, min_chars: int = 50) -> bool:
    """Quick check whether a PDF has meaningful extractable text.

    Returns True when the total extracted text across all pages exceeds
    ``min_chars`` — meaning the document has a usable digital text layer
    and does NOT need OCR.
    """
    text = _extract_pdf_text_fast(str(file_path))
    return len(text.strip()) > min_chars


def extract_pdf_page_count(file_path: str | Path) -> int:
    """Return the number of pages in a PDF without doing full extraction."""
    try:
        import fitz
        with fitz.open(str(file_path)) as doc:
            return len(doc)
    except Exception:
        return 0


# ── Office extraction ──────────────────────────────────────────────

def extract_docx_text(file_path: str | Path) -> str:
    """Extract structured text from .docx using python-docx."""
    try:
        from docx import Document
    except ImportError:
        return ""
    try:
        doc = Document(str(file_path))
        parts: list[str] = []
        for p in doc.paragraphs:
            if p.text and p.text.strip():
                style = p.style.name if p.style else ""
                if "heading" in (style or "").lower() or "title" in (style or "").lower():
                    # Approximate heading level from font size
                    level = 1
                    for run in p.runs:
                        if run.font.size and run.font.size.pt:
                            if run.font.size.pt >= 18:
                                level = 1
                            elif run.font.size.pt >= 14:
                                level = 2
                            break
                    parts.append(f"{'#' * level} {p.text.strip()}")
                else:
                    parts.append(p.text.strip())

        # Include table content
        for table in doc.tables:
            rows: list[str] = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                parts.append("\n\n" + "\n".join(rows))

        return "\n\n".join(parts)
    except Exception:
        return _extract_markitdown(str(file_path))


def extract_xlsx_text(file_path: str | Path) -> str:
    """Extract text from .xlsx as GFM tables using openpyxl."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return ""
    path = Path(file_path)
    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
        sheets: list[str] = []
        for sheet_name in wb.sheetnames[:10]:  # cap at 10 sheets
            ws = wb[sheet_name]
            rows: list[str] = []
            for row in ws.iter_rows(values_only=True):
                row_text = "| " + " | ".join(str(c) if c is not None else "" for c in row) + " |"
                if row_text.strip("| "):
                    rows.append(row_text)
            if rows:
                sheets.append(f"## Sheet: {sheet_name}\n\n" + "\n".join(rows))
        wb.close()
        return "\n\n".join(sheets)
    except Exception:
        return _extract_markitdown(str(path))


def extract_pptx_text(file_path: str | Path) -> str:
    """Extract text from .pptx using python-pptx."""
    try:
        from pptx import Presentation
    except ImportError:
        return ""
    try:
        prs = Presentation(str(file_path))
        slides: list[str] = []
        for i, slide in enumerate(prs.slides):
            slide_text: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for p in shape.text_frame.paragraphs:
                        if p.text.strip():
                            slide_text.append(p.text.strip())
            if slide_text:
                slides.append(f"### Slide {i + 1}\n\n" + "\n".join(slide_text))
        return "\n\n".join(slides)
    except Exception:
        return _extract_markitdown(str(file_path))


def extract_text_file(file_path: str | Path) -> str:
    """Read a text file with multi-encoding fallback chain."""
    path = Path(file_path)
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def extract_markitdown(file_path: str | Path) -> str:
    """Extract text via Microsoft markitdown (fallback for EPUB, old Office, etc.)."""
    return _extract_markitdown(str(file_path))


# ── Image extraction ──────────────────────────────────────────────

def extract_image_text(file_path: str | Path, *, trace_id: str = "") -> str:
    """Extract text from an image file via OpenCV preprocessing + LLM OCR.

    Steps:
      1. Read raw bytes
      2. OpenCV preprocess (deskew, denoise, CLAHE, threshold)
      3. OCR via Ollama MiniCPM-V / rkllama NPU
      4. If full-image OCR fails, try horizontal segment-based OCR

    This function is sync-safe — it blocks the calling thread while
    waiting for OCR HTTP responses (via asyncio.run() internally).
    """
    import asyncio as _asyncio
    import base64 as _base64

    path = Path(file_path)
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        return ""

    try:
        from tutor_platform.tools.preprocess import preprocess_image_bytes
        processed = preprocess_image_bytes(raw_bytes)
    except Exception:
        processed = raw_bytes

    # ── Run async OCR inside a temporary event loop ──
    async def _do_ocr() -> str:
        # Try full-image OCR first
        text = await _ocr_bytes_async(processed, trace_id)
        if text:
            return text

        # Full-image failed → split into horizontal segments and OCR in parallel
        segments = _split_image_segments(processed)
        if len(segments) <= 1:
            return text

        logger.debug(
            "[%s] Splitting image into %d segments for parallel OCR",
            trace_id, len(segments),
        )
        tasks = [_ocr_bytes_async(seg, trace_id) for seg in segments]
        results = await _asyncio.gather(*tasks)
        combined = "\n".join(r for r in results if r)
        if combined:
            logger.debug(
                "[%s] Segment OCR: %d chars from %d/%d segments",
                trace_id, len(combined), sum(1 for r in results if r), len(results),
            )
            return combined
        return text

    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return _asyncio.run(_do_ocr())

    # Running loop exists — delegate to a thread
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_asyncio.run, _do_ocr).result()


async def _ocr_bytes_async(image_bytes: bytes, trace_id: str) -> str:
    """OCR image bytes via Ollama MiniCPM-V → rkllama NPU fallback.

    Reuses the same endpoints as the MiniCPM OCR adapter in ocr_adapters.py.
    """
    import base64 as _base64
    import httpx as _httpx

    # Preprocessing already applied by caller
    img_b64 = _base64.b64encode(image_bytes).decode("utf-8")

    provider = os.environ.get("OCR_PROVIDER", "rkllama")
    if provider == "ollama":
        ollama_url = os.environ.get("OLLAMA_URL", "http://ollama:11434")
        model = os.environ.get("OLLAMA_OCR_MODEL", "openbmb/minicpm-v4.6:q4_K_M")
        keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "15m")
        try:
            async with _httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "你是一个专业OCR文字识别引擎。\n\n"
                                    "规则：\n"
                                    "1. 只输出图片中实际存在的文字\n"
                                    "2. 中文文字直接输出纯文本\n"
                                    "3. 数学公式用$LaTeX$行内或$$display$$块级\n"
                                    "4. 保留原始换行和段落结构\n"
                                    "5. 如果没有文字，返回空字符串"
                                ),
                            },
                            {
                                "role": "user",
                                "content": "识别这张图片中的所有文字，只输出文字本身：",
                                "images": [img_b64],
                            },
                        ],
                        "stream": False,
                        "keep_alive": keep_alive,
                        "options": {"temperature": 0},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = (data.get("message", {}).get("content", "") or "").strip()
                    import re as _re
                    m = _re.search(r'[一-鿿]|\$\$?|\\\\\[', content)
                    if m:
                        content = content[m.start():]
                    else:
                        content = _re.sub(
                            r'^[\s\n]*(?:图片[中的上].*?[：:]|识别结果[：:]|'
                            r'OCR[识别结果]*[：:]|the (?:ocr|text|image).*?[：:])',
                            '', content, flags=_re.IGNORECASE,
                        )
                    content = _re.sub(r'^[\s\n：:，,;.、]+', '', content).strip()
                    return content
                logger.warning("[%s] Ollama OCR HTTP %s", trace_id, resp.status_code)
        except Exception as exc:
            logger.warning("[%s] Ollama OCR failed: %s", trace_id, exc)
    else:
        rkllama_url = os.environ.get("RKLLAMA_URL", "http://rkllama:8080")
        try:
            async with _httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{rkllama_url}/v1/ocr",
                    json={
                        "image": img_b64,
                        "language": "zh",
                        "return_formulas": False,
                        "return_layout": False,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return (data.get("text", "") or "").strip()
                logger.warning("[%s] rkllama OCR HTTP %s", trace_id, resp.status_code)
        except Exception as exc:
            logger.warning("[%s] rkllama OCR failed: %s", trace_id, exc)

    return ""


def _split_image_segments(image_bytes: bytes) -> list[bytes]:
    """Split a page image at horizontal whitespace gaps.

    Uses horizontal projection to detect text row gaps (blank lines between
    questions/paragraphs). Returns the original image as single-element list
    when no split is possible.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return [image_bytes]

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return [image_bytes]

    h, w = img.shape
    _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    proj = np.sum(binary, axis=1) // 255
    threshold_px = max(1, int(w * 0.01))
    content = proj > threshold_px

    min_gap_h = max(5, int(h * 0.005))
    segments: list[bytes] = []
    i = 0
    while i < h:
        if not content[i]:
            i += 1
            continue
        start = i
        while i < h and content[i]:
            i += 1
        end = i
        gap_end = i
        while gap_end < h and not content[gap_end]:
            gap_end += 1
        if gap_end - i >= min_gap_h and end - start >= 40:
            seg = img[max(0, start - 2): min(h, gap_end + 2)]
            _, buf = cv2.imencode(".jpg", seg, [cv2.IMWRITE_JPEG_QUALITY, 90])
            segments.append(buf.tobytes())
            i = gap_end

    if len(segments) <= 1:
        return [image_bytes]
    return segments


# ── PDF table extraction ──────────────────────────────────────────

def extract_pdf_tables(file_path: str | Path, max_pages: int = 50) -> list[dict]:
    """Extract structured table data from a PDF using PyMuPDF ``find_tables()``.

    Returns a list of dicts, each representing one table:
      - ``page``: 0-based page index
      - ``bbox``: table bounding box as ``[x0, y0, x1, y1]``
      - ``row_count``, ``col_count``: table dimensions
      - ``header``: list of column header strings (if detectable)
      - ``rows``: list of lists of cell text

    No Tesseract dependency — tables are detected from text/graphics layout.
    """
    path = Path(file_path)
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not available for table extraction")
        return []

    tables: list[dict] = []
    try:
        doc = fitz.open(str(path))
        pages_to_check = min(max_pages, len(doc))
        for i in range(pages_to_check):
            page = doc[i]
            found = page.find_tables()
            if not found or not found.tables:
                continue
            for tab in found.tables:
                rows_data: list[list[str]] = []
                header_row: list[str] = []
                for row in tab.extract():
                    cells = [str(cell).strip() if cell is not None else "" for cell in row]
                    if cells and all(cells):
                        rows_data.append(cells)
                if not rows_data:
                    continue
                # First non-empty row is likely the header
                header_row = rows_data[0] if rows_data else []
                data_rows = rows_data[1:] if len(rows_data) > 1 else []
                tables.append({
                    "page": i,
                    "bbox": list(tab.bbox) if hasattr(tab, "bbox") else [],
                    "row_count": len(rows_data),
                    "col_count": len(header_row) if header_row else 0,
                    "header": header_row,
                    "rows": data_rows,
                })
        doc.close()
    except Exception as exc:
        logger.warning("PDF table extraction failed for %s: %s", path.name, exc)

    if tables:
        logger.debug("extract_pdf_tables: %d tables from %s", len(tables), path.name)
    return tables


def extract_pdf_tables_as_markdown(file_path: str | Path, max_pages: int = 50) -> str:
    """Extract PDF tables as GFM Markdown string for appending to extracted text."""
    tables = extract_pdf_tables(file_path, max_pages=max_pages)
    if not tables:
        return ""

    lines = ["\n\n## Tables\n"]
    for i, tab in enumerate(tables):
        lines.append(f"\n### Table {i + 1} (page {tab['page'] + 1})\n")
        header = tab["header"]
        rows = tab["rows"]
        if header:
            lines.append("| " + " | ".join(header) + " |")
            lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ── PDF embedded image extraction ─────────────────────────────────

def extract_pdf_embedded_images(file_path: str | Path, max_pages: int = 50) -> list[bytes]:
    """Extract embedded images from a PDF using ``doc.get_page_images()``.

    Returns raw image bytes for each embedded image found.  Caller can
    pass these to an OCR engine for text extraction from embedded graphics.
    """
    path = Path(file_path)
    try:
        import fitz
    except ImportError:
        return []

    images: list[bytes] = []
    try:
        doc = fitz.open(str(path))
        pages_to_check = min(max_pages, len(doc))
        for i in range(pages_to_check):
            page = doc[i]
            image_list = page.get_images(full=True)
            for img in image_list:
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image.get("image")
                if image_bytes and len(image_bytes) > 500:
                    images.append(image_bytes)
        doc.close()
    except Exception as exc:
        logger.warning("PDF image extraction failed for %s: %s", path.name, exc)

    if images:
        logger.debug("extract_pdf_embedded_images: %d images from %s", len(images), path.name)
    return images


# ── HTML sanitization ─────────────────────────────────────────────

def _sanitize_html(html_text: str) -> str:
    """Strip dangerous HTML elements keeping only safe text content.

    Removes scripts, event handlers, iframes, objects, and style blocks
    to prevent XSS when content is displayed in any web context.
    """
    import re as _re

    cleaned = _re.sub(r"<script[^>]*>.*?</script>", "", html_text,
                      flags=_re.DOTALL | _re.IGNORECASE)
    cleaned = _re.sub(r"<style[^>]*>.*?</style>", "", cleaned,
                      flags=_re.DOTALL | _re.IGNORECASE)
    cleaned = _re.sub(r"<iframe[^>]*>.*?</iframe>", "", cleaned,
                      flags=_re.DOTALL | _re.IGNORECASE)
    cleaned = _re.sub(r"<object[^>]*>.*?</object>", "", cleaned,
                      flags=_re.DOTALL | _re.IGNORECASE)
    cleaned = _re.sub(r"<embed[^>]*>.*?</embed>", "", cleaned,
                      flags=_re.DOTALL | _re.IGNORECASE)
    cleaned = _re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', "", cleaned,
                      flags=_re.IGNORECASE)
    cleaned = _re.sub(r"\s+on\w+\s*=\s*\S+", "", cleaned, flags=_re.IGNORECASE)
    return cleaned


# ── Unified dispatch ───────────────────────────────────────────────

# Extension → best extractor mapping.  The canonical source of truth.
# All ingestion paths MUST call extract_text() to guarantee consistent behaviour.
_EXTRACTOR_MAP: dict[str, str] = {
    # PDF — pymupdf4llm → pymupdf fallback (OCR via ocr_enabled param)
    ".pdf":  "pdf",
    # Modern Office — dedicated libraries → markitdown fallback
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".pptm": "pptx",
    ".ppsx": "pptx",
    # Old Office — markitdown only
    ".doc":  "markitdown",
    ".ppt":  "markitdown",
    ".pps":  "markitdown",
    ".xls":  "markitdown",
    ".odt":  "markitdown",
    ".rtf":  "markitdown",
    # Images — OpenCV preprocess + LLM OCR
    ".jpg":  "image",
    ".jpeg": "image",
    ".png":  "image",
    ".gif":  "image",
    ".webp": "image",
    ".bmp":  "image",
    ".tiff": "image",
    ".tif":  "image",
    ".heic": "image",
    # Markitdown formats
    ".epub": "markitdown",
    ".zip":  "markitdown",
    ".mp3":  "markitdown",
    ".wav":  "markitdown",
    ".ogg":  "markitdown",
    # HTML — needs sanitization
    ".html": "html",
    ".htm":  "html",
}


def extract_text(file_path: str | Path, *, trace_id: str = "") -> str:
    """Extract text from any supported document as structured Markdown.

    Automatically selects the best extraction tool based on file extension:
      - .pdf  → pymupdf4llm.to_markdown() (structured Markdown, no OCR by default)
      - .docx → python-docx (headings + tables)
      - .xlsx → openpyxl (GFM tables per sheet)
      - .pptx → python-pptx (slide-by-slide)
      - .jpg/.png/… → OpenCV preprocess + LLM OCR (MiniCPM-V / rkllama)
      - .html → multi-encoding read + XSS sanitization
      - .txt/.md/.py/… → multi-encoding read
      - .doc/.ppt/.xls/.odt/.rtf/.epub → markitdown fallback
      - Others → best-effort text read

    Returns empty string when no text could be extracted.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    dispatch = _EXTRACTOR_MAP.get(ext, "text")

    if dispatch == "pdf":
        text = extract_pdf_text(path)
        # Cross-validation: if pymupdf4llm returned nothing, try markitdown
        if not text:
            logger.debug("pymupdf4llm returned empty for %s, trying markitdown fallback", path.name)
            text = extract_markitdown(path)
        return text
    elif dispatch == "docx":
        return extract_docx_text(path)
    elif dispatch == "xlsx":
        return extract_xlsx_text(path)
    elif dispatch == "pptx":
        return extract_pptx_text(path)
    elif dispatch == "image":
        return extract_image_text(path, trace_id=trace_id)
    elif dispatch == "html":
        text = extract_text_file(path)
        return _sanitize_html(text) if text else ""
    elif dispatch == "markitdown":
        return extract_markitdown(path)

    # Fallback: try as plain text first, then markitdown
    text = extract_text_file(path)
    if not text and ext not in {
        ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv",
        ".html", ".htm", ".xml", ".css", ".log", ".sh", ".cfg", ".ini", ".env",
        ".toml", ".sql", ".tex", ".java", ".c", ".h", ".cpp", ".go", ".rs",
        ".rb", ".php", ".pl", ".lua", ".r", ".swift", ".kt", ".scala", ".dart",
        ".hs", ".clj", ".ex", ".erl", ".ml", ".fs", ".sol", ".proto", ".tf",
    }:
        text = extract_markitdown(path)
    return text or ""


# ── Internal helpers ───────────────────────────────────────────────

def _extract_pdf_text_fast(file_path: str) -> str:
    """Extract text from a PDF via pymupdf page.get_text() (fast, no LLM)."""
    try:
        import fitz
    except ImportError:
        return ""
    try:
        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            pages.append(f"--- Page {page.number + 1} ---\n{page.get_text().strip()}")
        doc.close()
        return "\n\n".join(pages)
    except Exception:
        return ""


def _extract_markitdown(path_str: str) -> str:
    """Extract text via Microsoft markitdown."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return ""
    try:
        md = MarkItDown()
        result = md.convert(path_str)
        return result.text_content if result else ""
    except Exception:
        return ""


# ── Semantic chunking ───────────────────────────────────────────────

def semantic_chunk(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int = 100,
    doc_type: str = "unknown",
    filename: str = "",
) -> list[dict]:
    """Split text into semantic chunks preserving Markdown heading boundaries.

    Strategy (in priority order):
      1. Split at ``##`` / ``###`` / ``####`` Markdown headings (preserve
         knowledge-point boundaries).
      2. If resulting chunk > chunk_size, split at ``\\\\n\\\\n`` paragraphs.
      3. Last resort: hard split at chunk_size.

    Each chunk dict contains:
      - ``text``: the chunk content (with overlap prefix)
      - ``heading_path``: breadcrumb of parent headings
      - ``chunk_index``: 0-based chunk number
      - ``char_count``: length of this chunk's own text (excludes overlap)
      - ``doc_type``, ``filename``: metadata passthrough

    ``chunk_size`` defaults to ``RAG_CHUNK_SIZE`` env var or 800.
    """
    import re as _re

    if chunk_size is None:
        chunk_size = int(os.environ.get("RAG_CHUNK_SIZE", "800"))

    if len(text) <= chunk_size:
        return [{
            "text": text,
            "heading_path": "",
            "chunk_index": 0,
            "char_count": len(text),
            "doc_type": doc_type,
            "filename": filename,
        }]

    # Split at Markdown headings (## / ### / ####) — each starts a new section
    heading_re = _re.compile(r"^(#{2,4})\s+(.+)$", _re.MULTILINE)
    lines = text.split("\n")
    sections: list[tuple[str, str]] = []  # [(heading_path, body_text)]
    current_heading = ""
    current_body: list[str] = []

    heading_stack: list[tuple[int, str]] = []  # [(level, title)]

    for line in lines:
        m = heading_re.match(line.strip())
        if m and line.startswith("#"):
            # Flush current section
            if current_body:
                body_text = "\n".join(current_body).strip()
                if body_text:
                    sections.append((current_heading, body_text))
                current_body = []

            level = len(m.group(1))
            title = m.group(2).strip()

            # Pop headings that are same or deeper level
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            current_heading = " > ".join(t for _, t in heading_stack)
        else:
            current_body.append(line)

    # Flush final section
    if current_body:
        body_text = "\n".join(current_body).strip()
        if body_text:
            sections.append((current_heading, body_text))

    # Build chunks from sections, splitting oversized ones
    chunks: list[dict] = []
    for heading, body in sections:
        if len(body) <= chunk_size:
            chunks.append({
                "text": body,
                "heading_path": heading,
                "chunk_index": len(chunks),
                "char_count": len(body),
                "doc_type": doc_type,
                "filename": filename,
            })
        else:
            # Split oversized body at paragraph boundaries
            paragraphs = _re.split(r"\n\s*\n", body)
            buf = ""
            buf_heading = heading
            for para in paragraphs:
                if len(buf) + len(para) + 2 > chunk_size and buf:
                    chunks.append({
                        "text": buf.strip(),
                        "heading_path": buf_heading,
                        "chunk_index": len(chunks),
                        "char_count": len(buf.strip()),
                        "doc_type": doc_type,
                        "filename": filename,
                    })
                    buf = para
                else:
                    buf = (buf + "\n\n" + para).strip() if buf else para
            if buf.strip():
                chunks.append({
                    "text": buf.strip(),
                    "heading_path": heading,
                    "chunk_index": len(chunks),
                    "char_count": len(buf.strip()),
                    "doc_type": doc_type,
                    "filename": filename,
                })

    # Apply overlap: prepend tail of previous chunk
    if chunk_overlap > 0 and len(chunks) > 1:
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]["text"]
            if len(prev) > chunk_overlap:
                overlap = prev[-chunk_overlap:]
                # Find a clean break point
                nl = overlap.find("\n")
                if nl > chunk_overlap // 2:
                    overlap = overlap[nl + 1:]
                chunks[i]["text"] = overlap + "\n" + chunks[i]["text"]

    return chunks
