"""Unified document processing pipeline — single entry point for all ingestion paths.

Routes every file through classification → extraction → optional structuring,
producing standardized sidecar files regardless of the original entry point
(Web KB upload, WeChat, MCP tools, CLI, chat attachments, API calls).

Usage::

    result = await UnifiedDocumentPipeline.process("/path/to/file.pdf")
    # → produces .txt and/or .exam.json sidecar next to the original file
"""

from __future__ import annotations

import asyncio
import logging
import os
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from tutor_platform.rag.extractors import (
    extract_docx_text,
    extract_markitdown,
    extract_pdf_text,
    extract_pptx_text,
    extract_text,
    extract_text_file,
    extract_xlsx_text,
    has_pdf_text_layer,
)
from tutor_platform.tools.preprocess import preprocess_image_bytes

if TYPE_CHECKING:
    from deeptutor.services.llm.client import LLMClient


# ── File classification ─────────────────────────────────────────

class DocType(str, Enum):
    """Document type determined by extension + content sniffing."""

    TEXT = "text"               # .txt, .md, .csv, .json, etc.
    IMAGE = "image"             # .jpg, .png, .webp, etc.
    TEXT_PDF = "text_pdf"        # PDF with extractable text layer
    SCANNED_PDF = "scanned_pdf"   # PDF without text layer
    EXAM_PDF = "exam_pdf"        # PDF that looks like an exam (multi-page, contains questions)
    OFFICE_DOCX = "office_docx"   # .docx
    OFFICE_XLSX = "office_xlsx"   # .xlsx, .xls
    OFFICE_PPTX = "office_pptx"   # .pptx, .ppt
    OFFICE_OLD = "office_old"     # .doc, .ppt, .xls
    OFFICE_OTHER = "office_other"  # .odt, .rtf, .pdf (text), etc.
    UNKNOWN = "unknown"


# Extension → DocType mapping (fast path, no content sniffing)
_EXT_TYPE_MAP: dict[str, DocType] = {
    ".txt": DocType.TEXT, ".md": DocType.TEXT, ".csv": DocType.TEXT,
    ".json": DocType.TEXT, ".yaml": DocType.TEXT, ".yml": DocType.TEXT,
    ".xml": DocType.TEXT, ".html": DocType.TEXT, ".htm": DocType.TEXT,
    ".py": DocType.TEXT, ".js": DocType.TEXT, ".ts": DocType.TEXT,
    ".css": DocType.TEXT, ".log": DocType.TEXT,
    ".jpg": DocType.IMAGE, ".jpeg": DocType.IMAGE, ".png": DocType.IMAGE,
    ".gif": DocType.IMAGE, ".webp": DocType.IMAGE, ".bmp": DocType.IMAGE,
    ".tiff": DocType.IMAGE, ".tif": DocType.IMAGE, ".heic": DocType.IMAGE,
    ".docx": DocType.OFFICE_DOCX,
    ".doc": DocType.OFFICE_OLD,
    ".xlsx": DocType.OFFICE_XLSX,
    ".xls": DocType.OFFICE_OLD,
    ".pptx": DocType.OFFICE_PPTX, ".pptm": DocType.OFFICE_PPTX,
    ".ppt": DocType.OFFICE_OLD, ".pps": DocType.OFFICE_OLD, ".ppsx": DocType.OFFICE_PPTX,
    ".odt": DocType.OFFICE_OTHER, ".rtf": DocType.OFFICE_OTHER,
}


def classify_file(file_path: str | Path) -> DocType:
    """Classify a file by extension and content sniffing.

    PDFs get further classified into text_pdf / scanned_pdf / exam_pdf.
    """
    ext = os.path.splitext(str(file_path))[1].lower()
    doc_type = _EXT_TYPE_MAP.get(ext, DocType.UNKNOWN)

    if doc_type == DocType.UNKNOWN and ext == ".pdf":
        return _classify_pdf(file_path)

    return doc_type


def _classify_pdf(file_path: str | Path) -> DocType:
    """Open a PDF with pymupdf and decide text-layer vs scanned."""
    try:
        import fitz
    except ImportError:
        return DocType.SCANNED_PDF

    path = Path(file_path)
    try:
        doc = fitz.open(path)
    except Exception:
        return DocType.SCANNED_PDF

    try:
        total_chars = 0
        image_blocks = 0
        for page in doc:
            text = page.get_text()
            total_chars += len(text.strip())

            blocks = page.get_text("dict").get("blocks", [])
            image_blocks += sum(1 for b in blocks if b.get("type") == 1)

        # Heuristics for exam PDF:
        # - Multi-page (>2) with image blocks (questions with figures)
        # - OR single-page with both text AND at least one image block
        is_exam = (len(doc) > 2 and image_blocks > 0) or (image_blocks > 0 and total_chars > 200)

        if is_exam:
            return DocType.EXAM_PDF

        if total_chars > 100:
            return DocType.TEXT_PDF
        else:
            return DocType.SCANNED_PDF
    finally:
        doc.close()


# ── Unified pipeline result ──────────────────────────────────────

class PipelineResult:
    """Result of running the unified pipeline on a single file."""

    __slots__ = (
        "file_path", "doc_type", "content_text", "sidecar_paths",
        "error", "stats",
    )

    def __init__(
        self,
        file_path: str,
        doc_type: DocType,
        content_text: str | None = None,
        sidecar_paths: list[str] | None = None,
        error: str | None = None,
        stats: dict | None = None,
    ) -> None:
        self.file_path = file_path
        self.doc_type = doc_type
        self.content_text = content_text
        self.sidecar_paths = sidecar_paths or []
        self.error = error
        self.stats = stats or {}

    @property
    def ok(self) -> bool:
        return self.error is None


# ── Unified pipeline ─────────────────────────────────────────────

class UnifiedDocumentPipeline:
    """Process any document through classification → extraction → structuring.

    Produces standardized sidecar files alongside the original:

    - ``.txt`` — plain-text extraction (all document types)
    - ``.exam.json`` — structured exam paper (exam PDFs only)
    - ``.figures/`` — clipped figure PNGs (exam PDFs with images)

    Usage::

        result = await UnifiedDocumentPipeline.process("/tmp/exam.pdf")
        print(result.content_text)       # extracted plain text
        print(result.sidecar_paths)       # [".txt", ".exam.json"]
    """

    @classmethod
    async def process(
        cls,
        file_path: str | Path,
        *,
        llm_client: "LLMClient | None" = None,
        enable_structured_exam: bool = True,
        max_exam_pages: int = 50,
    ) -> PipelineResult:
        """Run the unified pipeline on a single file.

        Args:
            file_path: Path to the file to process.
            llm_client: Optional LLMClient for multimodal OCR/vision.
                        If None, text extraction is best-effort without LLM.
            enable_structured_exam: When True, run Phase 1-4 for exam PDFs.
            max_exam_pages: Maximum pages to process for exam PDFs.
        """
        path = Path(file_path)
        stats: dict = {"file_type": None, "extraction_chars": 0, "sidecars": []}

        if not path.is_file():
            return PipelineResult(
                file_path=str(path),
                doc_type=DocType.UNKNOWN,
                error=f"File not found: {file_path}",
            )

        # 1. Classify
        doc_type = classify_file(path)
        stats["file_type"] = doc_type.value
        logger.info("Unified pipeline: %s → %s", path.name, doc_type.value)

        # 2. Extract text
        content_text: str | None = None
        sidecar_paths: list[str] = []

        try:
            if doc_type in (DocType.TEXT_PDF, DocType.SCANNED_PDF, DocType.EXAM_PDF):
                content_text = await cls._extract_pdf_text(path, doc_type, llm_client, stats)
            elif doc_type == DocType.IMAGE:
                content_text = await cls._extract_image_text(path, llm_client, stats)
            else:
                # All other types: unified dispatch via extractors.py
                content_text = await asyncio.get_running_loop().run_in_executor(
                    None, extract_text, path,
                )

            stats["extraction_chars"] = len(content_text) if content_text else 0
        except Exception as exc:
            logger.error("Extraction failed for %s: %s", path.name, exc)
            return PipelineResult(
                file_path=str(path), doc_type=doc_type,
                error=f"Extraction failed: {exc}", stats=stats,
            )

        if not content_text:
            return PipelineResult(
                file_path=str(path), doc_type=doc_type,
                content_text="", stats=stats,
            )

        # 3. Write markdown sidecar
        md_path = cls._write_sidecar(path, content_text, suffix=".md")
        if md_path:
            sidecar_paths.append(md_path)
            stats["sidecars"].append(".md")

        # 4. Structured exam pipeline (Phase 1-4) for exam PDFs
        if enable_structured_exam and doc_type == DocType.EXAM_PDF and llm_client:
            try:
                exam_json = await cls._run_exam_pipeline(
                    path, llm_client, max_exam_pages, stats,
                )
                if exam_json:
                    json_path = cls._write_sidecar_raw(path, exam_json, suffix=".exam.json")
                    if json_path:
                        sidecar_paths.append(json_path)
                        stats["sidecars"].append(".exam.json")
            except Exception as exc:
                logger.error("Exam pipeline failed for %s: %s", path.name, exc)
                stats["exam_pipeline_error"] = str(exc)

        return PipelineResult(
            file_path=str(path),
            doc_type=doc_type,
            content_text=content_text,
            sidecar_paths=sidecar_paths,
            stats=stats,
        )

    # ── Per-type extractors ──────────────────────────────────────

    @classmethod
    async def _extract_pdf_text(
        cls, path: Path, doc_type: DocType, llm_client, stats: dict,
    ) -> str | None:
        """Extract text from any PDF type via pymupdf4llm + MiniCPM-V OCR.

        Uses ``extract_pdf_text(ocr_enabled=True)`` which delegates to
        pymupdf4llm's hybrid OCR pipeline: text-layer pages pass through
        unchanged, scanned regions are OCR'd via MiniCPM-V / rkllama.
        No Tesseract required.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: extract_pdf_text(path, ocr_enabled=True),
        )

    @classmethod
    async def _extract_image_text(
        cls, path: Path, llm_client, stats: dict,
    ) -> str | None:
        """OCR an image file with OpenCV preprocessing."""
        if llm_client is None:
            return ""
        raw_bytes = path.read_bytes()
        processed = preprocess_image_bytes(raw_bytes)
        img_b64 = _to_base64(processed)
        try:
            result = await asyncio.wait_for(
                llm_client.complete(
                    "Transcribe all text from this image. Return only the text.",
                    image_data=img_b64,
                    image_mime_type="image/jpeg",
                    image_filename=path.name,
                ),
                timeout=120,
            )
            stats["ocr_called"] = 1
            stats["ocr_preprocessed"] = 1
            return result.strip()
        except asyncio.TimeoutError:
            logger.warning("OCR image %s timed out after 120s", path.name)
            return ""
        except Exception as exc:
            logger.warning("OCR image %s failed: %s", path.name, exc)
            return ""

    @classmethod
    async def _extract_office_text(cls, path: Path, stats: dict) -> str | None:
        """Extract text from Office documents — sync I/O runs in a thread pool."""
        loop = asyncio.get_running_loop()
        ext = path.suffix.lower()

        async def _run_sync(fn, *args):
            return await loop.run_in_executor(None, fn, *args)

        # Try python-docx/openpyxl/python-pptx first (faster, richer output)
        text: str | None = None
        if ext == ".docx":
            text = await _run_sync(extract_docx_text, path)
        elif ext == ".xlsx":
            text = await _run_sync(extract_xlsx_text, path)
        elif ext == ".pptx":
            text = await _run_sync(extract_pptx_text, path)
        else:
            text = await _run_sync(extract_markitdown, path)

        # If extraction failed, try markitdown as universal fallback
        if not text:
            text = await _run_sync(extract_markitdown, path)

        # Extract and describe embedded images from the document
        if text:
            img_descriptions = await _run_sync(_extract_office_images, path, ext)
            if img_descriptions:
                text = text + "\n\n" + img_descriptions

        return text

    @classmethod
    def _extract_text_file(cls, path: Path, stats: dict) -> str | None:
        """Read a text file with encoding detection."""
        for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                return path.read_text(encoding=encoding)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return path.read_text(encoding="utf-8", errors="replace")

    @classmethod
    def _extract_unknown(cls, path: Path, stats: dict) -> str | None:
        """Last-resort extraction for unknown file types."""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    # ── Exam pipeline ────────────────────────────────────────────

    @classmethod
    async def _run_exam_pipeline(
        cls, path: Path, llm_client, max_pages: int, stats: dict,
    ) -> str | None:
        """Run Phase 1-4 structured exam pipeline on a PDF."""
        from tutor_platform.rag.exam_pipeline import run_exam_pipeline, serialize_exam_paper_json

        exam_dict = await run_exam_pipeline(
            path, llm_client, max_pages=max_pages,
            save_figures=False, skip_non_exam=False,
        )
        if exam_dict is None:
            return None

        stats["exam_questions"] = len(exam_dict.get("questions", []))
        return serialize_exam_paper_json(exam_dict)

    # ── Sidecar helpers ──────────────────────────────────────────

    @classmethod
    def _write_sidecar(cls, file_path: Path, content: str, suffix: str) -> str | None:
        """Write a sidecar text file atomically."""
        sidecar = file_path.with_name(file_path.stem + suffix)
        tmp = sidecar.with_name(sidecar.name + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(str(tmp), str(sidecar))
            return str(sidecar)
        except OSError as exc:
            logger.warning("Failed to write sidecar %s: %s", sidecar, exc)
            return None

    @classmethod
    def _write_sidecar_raw(cls, file_path: Path, content: str, suffix: str) -> str | None:
        """Write a raw sidecar file (not text-transformed)."""
        return cls._write_sidecar(file_path, content, suffix)


# ── Office embedded image extraction ─────────────────────────────

def _extract_office_images(path: Path, ext: str) -> str | None:
    """Extract embedded images from Office docs (ZIP-based + OLE-based).

    Returns a concatenated description of all found images, or None if
    no images were found.
    """
    import os as _os
    all_images: list[bytes] = []
    seen: set[int] = set()

    # ZIP-based Office formats (docx, pptx, xlsx)
    media_prefixes = {
        ".docx": ["word/media/"], ".docm": ["word/media/"],
        ".pptx": ["ppt/media/"], ".pptm": ["ppt/media/"], ".ppsx": ["ppt/media/"],
        ".xlsx": ["xl/media/"],
    }.get(ext, [])

    for prefix in media_prefixes:
        all_images.extend(_extract_zip_images_from_path(path, prefix))

    # OLE-based old Office formats (.doc, .ppt, .xls)
    if ext in {".doc", ".ppt", ".pps", ".xls"}:
        all_images.extend(_extract_ole_images_from_path(path, seen))

    if not all_images:
        return None

    # Build a description section — no MiniCPM OCR needed here,
    # just note the images exist and their sizes for context
    lines = ["\n[文档内嵌图片]"]
    for i, img in enumerate(all_images[:8]):
        img_type = "PNG" if img[:4] == b"\x89PNG" else "JPEG" if img[:2] == b"\xff\xd8" else "Image"
        lines.append(f"- 图片{i+1}: {len(img)//1024}KB {img_type}")
    return "\n".join(lines)


def _extract_zip_images_from_path(file_path: Path, media_prefix: str) -> list[bytes]:
    """Extract image blobs from a ZIP-based Office document."""
    import zipfile, os as _os
    images: list[bytes] = []
    try:
        with zipfile.ZipFile(str(file_path)) as z:
            for name in z.namelist():
                ext_lower = _os.path.splitext(name)[1].lower()
                if name.startswith(media_prefix) and ext_lower in {
                    ".png", ".jpg", ".jpeg", ".gif", ".bmp",
                }:
                    data = z.read(name)
                    if len(data) > 500:
                        images.append(data)
    except (zipfile.BadZipFile, FileNotFoundError):
        pass
    return images


def _extract_ole_images_from_path(file_path: Path, seen: set[int]) -> list[bytes]:
    """Extract image blobs from an OLE-based Office document (.doc/.ppt/.xls)."""
    images: list[bytes] = []
    try:
        import olefile
    except ImportError:
        return images
    try:
        ole = olefile.OleFileIO(str(file_path))
        for s in ole.listdir():
            try:
                data = ole.openstream(s).read()
                h = hash(data)
                if h in seen:
                    continue
                sig = data[:8]
                if (
                    sig[:2] == b"\xff\xd8"
                    or sig[:4] == b"\x89PNG"
                    or sig[:2] == b"BM"
                    or sig[:4] == b"GIF8"
                ):
                    seen.add(h)
                    images.append(data)
            except Exception:
                continue
        ole.close()
    except Exception:
        pass
    return images


def _to_base64(data: bytes) -> str:
    """Encode bytes to base64 string."""
    import base64
    return base64.b64encode(data).decode("ascii")


def _guess_mime(path: Path) -> str:
    """Guess MIME type from extension."""
    ext = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "application/octet-stream")
