"""Phase 2: Block-level OCR and figure understanding via multimodal VL model.

Renders individual layout blocks as high-DPI images and sends them
to a multimodal LLM with targeted prompts depending on block type.

Key differences from the old per-page OCR:
- Text blocks → small clipped images → precise OCR + LaTeX formulas
- Geometry/figure blocks → structured description (type, vertices, labels)
- Same-page blocks run concurrently; different pages are sequential.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json as json_mod
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from tutor_platform.rag.layout_engine import (
    FigureHint,
    LayoutBlock,
    PageLayout,
)

if TYPE_CHECKING:
    from deeptutor.services.llm.client import LLMClient

logger = logging.getLogger(__name__)

try:
    import fitz
except ImportError:
    fitz = None  # type: ignore[assignment]


# ── Prompt catalogue ─────────────────────────────────────────────

# Text blocks: OCR focused on accuracy + LaTeX
_TEXT_OCR_PROMPT = (
    "You are an OCR engine for exam papers. "
    "Transcribe this image region EXACTLY as written, preserving every character, "
    "punctuation mark, line break, superscript and subscript. "
    "\n"
    "Rules:\n"
    "- Mathematical formulas: output as LaTeX inline ($$...$$) or display ($$$$...$$$$).\n"
    "- Chemical formulas: preserve subscripts (H₂SO₄ → H$_2$SO$_4$).\n"
    "- Chinese text: output as-is.\n"
    "- Do NOT answer or explain — ONLY transcribe.\n"
    "- Return the transcription and nothing else."
)

# Title / header blocks — add metadata extraction
_TITLE_OCR_PROMPT = (
    "You are an OCR engine for exam papers. "
    "Transcribe this header region exactly, then output a one-line JSON "
    "with metadata inferred from the text.\n"
    "Return ONLY:\n"
    '{"subject": "math|physics|chemistry", "grade": "grade7-12", '
    '"exam_type": "midterm|final|mock|monthly", "year": 2024, '
    '"text": "original header text"}\n'
    "If any field is unclear, use null."
)

# ── Figure descriptions per hint type ────────────────────────────

_GEOMETRY_DESCRIBE_PROMPT = (
    "Describe this geometry figure from an exam paper. "
    "Output a JSON object with these fields:\n"
    '- "figure_type": one of triangle|circle|quadrilateral|polygon|composite\n'
    '- "vertices": list of vertex labels (e.g. ["A","B","C"])\n'
    '- "given": list of known values from labels (sides, angles, coordinates)\n'
    '- "to_find_or_prove": what the question asks (from any text in the image)\n'
    '- "description": one-sentence summary in Chinese\n'
    "Return ONLY the JSON object."
)

_FUNCTION_GRAPH_DESCRIBE_PROMPT = (
    "Describe this function graph from an exam paper. "
    "Output a JSON object with these fields:\n"
    '- "function_hint": best-guess function type (linear|quadratic|cubic|trig|exponential|other)\n'
    '- "x_range": [min_x, max_x] approximate\n'
    '- "y_range": [min_y, max_y] approximate\n'
    '- "special_points": list of notable points with label and approximate coordinates, '
    'e.g. [{"label":"vertex","coord":[2,-4]}]\n'
    '- "description": one-sentence summary in Chinese\n'
    "Return ONLY the JSON object."
)

_TABLE_DESCRIBE_PROMPT = (
    "Extract this table as a Markdown table. Include column headers and all visible values. "
    "Return ONLY the Markdown table, nothing else."
)

_ILLUSTRATION_DESCRIBE_PROMPT = (
    "Describe this illustration/diagram from an exam paper. "
    "Output a JSON object with:\n"
    '- "type": schematic|experiment|chart|photo|flowchart|other\n'
    '- "elements": list of visible elements or labels\n'
    '- "description": one-sentence summary in Chinese\n'
    "Return ONLY the JSON object."
)

_FIGURE_PROMPTS: dict[FigureHint, str] = {
    FigureHint.GEOMETRY: _GEOMETRY_DESCRIBE_PROMPT,
    FigureHint.FUNCTION_GRAPH: _FUNCTION_GRAPH_DESCRIBE_PROMPT,
    FigureHint.TABLE: _TABLE_DESCRIBE_PROMPT,
    FigureHint.ILLUSTRATION: _ILLUSTRATION_DESCRIBE_PROMPT,
    FigureHint.UNKNOWN: _ILLUSTRATION_DESCRIBE_PROMPT,  # fallback
}


# ── Block content result ────────────────────────────────────────

class BlockContent:
    """OCR or description result for a single block."""

    __slots__ = ("block_id", "type", "text", "description",
                 "image_bytes", "error")

    def __init__(
        self,
        block_id: int,
        type: str,
        text: str | None = None,
        description: dict | None = None,
        image_bytes: bytes | None = None,
        error: str | None = None,
    ) -> None:
        self.block_id = block_id
        self.type = type              # "text" or "image"
        self.text = text              # OCR transcription
        self.description = description  # structured JSON for figures
        self.image_bytes = image_bytes  # clipped PNG (for later storage)
        self.error = error            # error message if failed

    @property
    def ok(self) -> bool:
        return self.error is None


# ── OCR engine ───────────────────────────────────────────────────

class BlockOCREngine:
    """Renders layout blocks as images and sends them to the configured VL model.

    Usage::

        layout = PaperLayoutEngine.process(path)
        ocr = BlockOCREngine(llm_client, pdf_path)
        page_results = await ocr.process_page(layout.pages[0])
        # page_results: list[BlockContent]
    """

    DPI: int = 300
    MAX_CONCURRENT_BLOCKS: int = 3  # per page

    def __init__(self, llm_client: "LLMClient", pdf_path: str | Path) -> None:
        if fitz is None:
            raise ImportError("PyMuPDF (fitz) is required for BlockOCREngine")
        self._llm = llm_client
        self._doc = fitz.open(pdf_path)

    def close(self) -> None:
        self._doc.close()

    # ── Public API ──────────────────────────────────────────────

    async def process_page(
        self,
        page_layout: PageLayout,
        save_figures: bool = False,
    ) -> list[BlockContent]:
        """Process all blocks on one page concurrently.

        Args:
            page_layout: Layout analysis from Phase 1.
            save_figures: When True, include `image_bytes` in results
                          so callers can persist them to disk.

        Returns:
            BlockContent list in reading order (same as page_layout.blocks).
        """
        page = self._doc[page_layout.page_num]
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_BLOCKS)

        async def process_one(block: LayoutBlock) -> BlockContent:
            async with semaphore:
                return await self._process_block(page, block, page_layout, save_figures)

        tasks = [process_one(b) for b in page_layout.blocks]
        return list(await asyncio.gather(*tasks))

    async def process_all_pages(
        self,
        layout_cache: "PaperLayoutCache",  # type: ignore[name-defined]
        save_figures: bool = False,
    ) -> list[list[BlockContent]]:
        """Process all pages in order. Pages are serial, blocks within a page are parallel."""
        all_results: list[list[BlockContent]] = []
        for page_layout in layout_cache.pages:
            logger.info(
                "OCR page %d/%d (%d blocks)",
                page_layout.page_num + 1,
                layout_cache.total_pages,
                len(page_layout.blocks),
            )
            page_results = await self.process_page(page_layout, save_figures=save_figures)
            all_results.append(page_results)
        return all_results

    # ── Per-block dispatch ──────────────────────────────────────

    async def _process_block(
        self,
        page,
        block: LayoutBlock,
        page_layout: PageLayout,
        save_figures: bool,
    ) -> BlockContent:
        """Render a block and send it to the VL model with the right prompt."""
        try:
            img_bytes = self._render_block(page, block)
            img_b64 = base64.b64encode(img_bytes).decode("ascii")
        except Exception as exc:
            return BlockContent(
                block_id=block.block_id,
                type=block.type,
                error=f"render failed: {exc}",
            )

        if block.type == "text" and block.needs_ocr:
            return await self._ocr_text_block(block, img_b64, img_bytes, save_figures)
        elif block.type == "image" and block.needs_description:
            return await self._describe_figure(block, img_b64, img_bytes, save_figures)
        else:
            # Block already has text or doesn't need processing
            return BlockContent(
                block_id=block.block_id,
                type=block.type,
                text=block.raw_text,
                image_bytes=img_bytes if save_figures else None,
            )

    # ── OCR for text blocks ─────────────────────────────────────

    async def _ocr_text_block(
        self,
        block: LayoutBlock,
        img_b64: str,
        img_bytes: bytes,
        save_figures: bool,
    ) -> BlockContent:
        """Send a text block image to the VL model for OCR."""
        try:
            result = await self._llm.complete(
                _TEXT_OCR_PROMPT,
                image_data=img_b64,
                image_mime_type="image/png",
                image_filename=f"block-{block.block_id}.png",
            )
            return BlockContent(
                block_id=block.block_id,
                type="text",
                text=result.strip(),
                image_bytes=img_bytes if save_figures else None,
            )
        except Exception as exc:
            return BlockContent(
                block_id=block.block_id,
                type="text",
                error=f"ocr failed: {exc}",
            )

    # ── Figure description ──────────────────────────────────────

    async def _describe_figure(
        self,
        block: LayoutBlock,
        img_b64: str,
        img_bytes: bytes,
        save_figures: bool,
    ) -> BlockContent:
        """Send a figure block image to the VL model for structured description."""
        prompt = _FIGURE_PROMPTS.get(block.figure_hint, _ILLUSTRATION_DESCRIBE_PROMPT)
        try:
            result = await self._llm.complete(
                prompt,
                image_data=img_b64,
                image_mime_type="image/png",
                image_filename=f"figure-{block.block_id}.png",
            )
            description = _safe_json_parse(result)
            return BlockContent(
                block_id=block.block_id,
                type="image",
                description=description,
                image_bytes=img_bytes if save_figures else None,
            )
        except Exception as exc:
            return BlockContent(
                block_id=block.block_id,
                type="image",
                error=f"describe failed: {exc}",
            )

    # ── Rendering ───────────────────────────────────────────────

    @classmethod
    def _render_block(cls, page, block: LayoutBlock) -> bytes:
        """Render a single block as a high-DPI PNG clip."""
        # Expand bbox slightly to avoid cutting off characters
        x0, y0, x1, y1 = block.bbox
        pad = 4  # points
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(page.rect.width, x1 + pad)
        y1 = min(page.rect.height, y1 + pad)

        clip = fitz.Rect(x0, y0, x1, y1)
        dpi_zoom = cls.DPI / 72.0
        mat = fitz.Matrix(dpi_zoom, dpi_zoom)
        pix = page.get_pixmap(matrix=mat, clip=clip)
        return pix.tobytes("png")

    @classmethod
    def render_block_static(cls, pdf_path: str | Path, page_num: int, block: LayoutBlock) -> bytes:
        """Render a single block without holding a document open."""
        doc = fitz.open(pdf_path)
        try:
            page = doc[page_num]
            return cls._render_block(page, block)
        finally:
            doc.close()


# ── JSON helper ─────────────────────────────────────────────────

def _safe_json_parse(text: str) -> dict:
    """Extract a JSON object from text that may have markdown fences or extra content."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    # Find the first '{' and last '}'
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json_mod.loads(text[start:end + 1])
        except json_mod.JSONDecodeError:
            pass
    return {"raw": text}
