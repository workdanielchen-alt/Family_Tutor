"""Phase 1: PDF layout engine using PyMuPDF — zero LLM calls.

Splits each page into layout blocks (text / image / mixed) and
classifies image blocks via vector drawing analysis so the
downstream OCR stage can use targeted prompts.

All analysis is CPU-only, ~100ms per page.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ── Public types ─────────────────────────────────────────────────

class FigureHint(str, Enum):
    """Figure type inferred from vector drawing analysis."""

    GEOMETRY = "geometry"         # Lines-dominant → geometric proof diagram
    FUNCTION_GRAPH = "function_graph"  # Curves-dominant → function plot
    TABLE = "table"               # Rectangles with grid → data table
    ILLUSTRATION = "illustration"  # Mixed / logo / photo / diagram
    UNKNOWN = "unknown"           # Cannot determine (render-based fallback)


@dataclass
class LayoutBlock:
    """A single region on a page identified by the layout engine."""

    block_id: int
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1) in points
    type: Literal["text", "image", "mixed", "vector"]
    # Text-specific
    raw_text: str | None = None          # from get_text() for text blocks
    font_sizes: list[float] = field(default_factory=list)
    avg_font_size: float = 0.0
    is_bold: bool = False
    # Image-specific
    figure_hint: FigureHint = FigureHint.UNKNOWN  # only for image blocks
    # Shared
    needs_ocr: bool = False              # True when raw_text is empty/sparse
    needs_description: bool = False      # True when image block needs MiniCPM


@dataclass
class PageLayout:
    """Layout analysis result for a single page."""

    page_num: int           # 0-based
    width: float
    height: float
    blocks: list[LayoutBlock]
    is_two_column: bool = False
    is_scanned: bool = False  # True if no text layer at all


@dataclass
class PaperLayoutCache:
    """File-level cache key to skip re-processing."""

    file_hash: str           # SHA-256 hex
    total_pages: int
    pages: list[PageLayout]


# ── Engine ───────────────────────────────────────────────────────

class PaperLayoutEngine:
    """Analyses PDF pages into LayoutBlock trees using PyMuPDF only.

    Usage::

        layout = PaperLayoutEngine.process("/path/to/exam.pdf")
        for page in layout.pages:
            for block in page.blocks:
                if block.needs_ocr:
                    ...
    """

    # DPI used for rendering image blocks during later OCR.
    # The layout engine itself doesn't render — it just analyses
    # text blocks and drawing vectors.
    DEFAULT_OCR_DPI: int = 300

    # Font-size ratio relative to page mode that signals a title/header.
    TITLE_FONT_RATIO: float = 1.4

    # Minimum characters for a text block to avoid OCR.
    TEXT_SELF_SUFFICIENT_CHARS: int = 10

    @classmethod
    def process(
        cls,
        pdf_path: str | Path,
    ) -> PaperLayoutCache:
        """Run full layout analysis on a PDF and return cached layout."""
        if fitz is None:
            raise ImportError("PyMuPDF (fitz) is required for PaperLayoutEngine")

        path = Path(pdf_path)
        data = path.read_bytes()
        file_hash = hashlib.sha256(data).hexdigest()

        doc = fitz.open(path)
        try:
            pages: list[PageLayout] = []
            for page_num in range(len(doc)):
                pages.append(cls._analyse_page(doc[page_num], page_num))

            return PaperLayoutCache(
                file_hash=file_hash,
                total_pages=len(doc),
                pages=pages,
            )
        finally:
            doc.close()

    # ── Per-page analysis ────────────────────────────────────────

    @classmethod
    def _analyse_page(cls, page, page_num: int) -> PageLayout:
        """Analyse a single page and return its PageLayout."""
        width = page.rect.width
        height = page.rect.height

        # 1. Extract text blocks from PyMuPDF's layout engine
        text_dict = page.get_text("dict")
        raw_blocks = text_dict.get("blocks", [])

        # 2. Analyse vector drawings for figure hints
        drawing_hints = cls._analyse_drawings(page)

        # 3. Build LayoutBlock list
        layout_blocks: list[LayoutBlock] = []
        text_chars_total = 0
        image_hint_index = 0

        for i, raw in enumerate(raw_blocks):
            btype = raw.get("type", -1)

            if btype == 0:  # text block
                lb = cls._build_text_block(i, raw)
                layout_blocks.append(lb)
                text_chars_total += len(lb.raw_text or "")
            elif btype == 1:  # image block
                hint = FigureHint.UNKNOWN
                if image_hint_index < len(drawing_hints):
                    hint = drawing_hints[image_hint_index]
                    image_hint_index += 1
                lb = LayoutBlock(
                    block_id=i,
                    bbox=tuple(raw["bbox"]),
                    type="image",
                    figure_hint=hint,
                    needs_description=True,
                )
                layout_blocks.append(lb)
            else:
                # Unknown type — skip or treat as text
                continue

        # 4. Determine if scanned (no meaningful text)
        is_scanned = text_chars_total < cls.TEXT_SELF_SUFFICIENT_CHARS

        # 5. Detect double-column layout
        is_two_column = cls._detect_two_column(layout_blocks, width)

        # 6. Mark blocks needing OCR
        for lb in layout_blocks:
            if lb.type == "text" and (
                lb.raw_text is None or len(lb.raw_text.strip()) < cls.TEXT_SELF_SUFFICIENT_CHARS
            ):
                lb.needs_ocr = True

        return PageLayout(
            page_num=page_num,
            width=width,
            height=height,
            blocks=layout_blocks,
            is_two_column=is_two_column,
            is_scanned=is_scanned,
        )

    @classmethod
    def _build_text_block(cls, block_id: int, raw: dict) -> LayoutBlock:
        """Build a LayoutBlock from a PyMuPDF text block dict."""
        bbox = tuple(raw["bbox"])
        lines = raw.get("lines", [])
        spans: list[dict] = []
        for line in lines:
            spans.extend(line.get("spans", []))

        raw_text = ""
        font_sizes: list[float] = []
        bold_count = 0
        for sp in spans:
            raw_text += sp.get("text", "")
            size = sp.get("size", 0)
            if size > 0:
                font_sizes.append(size)
            flags = sp.get("flags", 0)
            # Bit 3 (value 4) = bold in PDF font flags
            if flags & 4:
                bold_count += 1

        avg_font = sum(font_sizes) / len(font_sizes) if font_sizes else 0.0
        is_bold = bold_count > len(spans) * 0.5 if spans else False

        return LayoutBlock(
            block_id=block_id,
            bbox=bbox,
            type="text",
            raw_text=raw_text if raw_text else None,
            font_sizes=font_sizes,
            avg_font_size=avg_font,
            is_bold=is_bold,
        )

    # ── Vector drawing analysis ──────────────────────────────────

    @classmethod
    def _analyse_drawings(cls, page) -> list[FigureHint]:
        """Analyse page drawings and return a FigureHint per drawing cluster."""
        try:
            drawings = page.get_drawings()
        except Exception:
            return []

        hints: list[FigureHint] = []
        for dw in drawings:
            items = dw.get("items", [])
            if not items:
                hints.append(FigureHint.UNKNOWN)
                continue

            # Count primitive types
            lines = 0
            curves = 0
            rects = 0
            quads = 0
            for item in items:
                op = item[0]
                if op == "l":
                    lines += 1
                elif op in ("c", "qu"):
                    curves += 1
                elif op == "re":
                    rects += 1
                elif op == "quad":
                    quads += 1

            total = lines + curves + rects + quads
            if total == 0:
                hints.append(FigureHint.UNKNOWN)
                continue

            ratio_lines = lines / total
            ratio_curves = curves / total
            ratio_rects = rects / total

            if ratio_lines > 0.6:
                hints.append(FigureHint.GEOMETRY)
            elif ratio_curves > 0.4:
                hints.append(FigureHint.FUNCTION_GRAPH)
            elif ratio_rects > 0.5 and rects >= 4:
                hints.append(FigureHint.TABLE)
            else:
                hints.append(FigureHint.ILLUSTRATION)

        return hints

    # ── Column detection ─────────────────────────────────────────

    @classmethod
    def _detect_two_column(cls, blocks: list[LayoutBlock], page_width: float) -> bool:
        """Heuristic: if >30% text blocks have x0 > 45% page width, two-column."""
        if not blocks:
            return False
        text_blocks = [b for b in blocks if b.type == "text" and b.bbox[0] > 0]
        if len(text_blocks) < 4:
            return False
        right_count = sum(1 for b in text_blocks if b.bbox[0] > page_width * 0.45)
        return right_count > len(text_blocks) * 0.3

    # ── File hash ────────────────────────────────────────────────

    @classmethod
    def compute_file_hash(cls, pdf_path: str | Path) -> str:
        """Return SHA-256 hex for a PDF file."""
        data = Path(pdf_path).read_bytes()
        return hashlib.sha256(data).hexdigest()
