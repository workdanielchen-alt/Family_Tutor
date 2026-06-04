"""Shared structured exam paper pipeline — single implementation used by all paths.

Phase 1→4 (Layout → Block OCR → Structure → Serialize) for exam PDFs.
Both UnifiedDocumentPipeline and RagDocumentPipeline call run_exam_pipeline().
"""

from __future__ import annotations

import json as json_mod
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.services.llm.client import LLMClient
    from tutor_platform.rag.exam_structurer import ExamPaper

logger = logging.getLogger(__name__)

from tutor_platform.rag.layout_engine import PaperLayoutEngine
from tutor_platform.rag.block_ocr import BlockOCREngine
from tutor_platform.rag.exam_structurer import ExamStructurer


async def run_exam_pipeline(
    pdf_path: str | Path,
    llm_client: "LLMClient",
    *,
    max_pages: int = 50,
    save_figures: bool = True,
    skip_non_exam: bool = True,
) -> dict | None:
    """Run the full structured exam pipeline on a PDF.

    Phases:
      1. Layout analysis (PaperLayoutEngine, no LLM)
      2. Block-level OCR (BlockOCREngine → MiniCPM)
      3. Semantic structuring (ExamStructurer, no LLM)
      4. Serialize to dict

    Args:
        pdf_path: Path to the exam PDF.
        llm_client: Multimodal LLM client for block OCR.
        max_pages: Maximum pages to process (capped at ``max_pages``).
        save_figures: When True, save clipped figures to ``.figures/`` directory.
        skip_non_exam: When True, skip PDFs that don't look like exams (no images
                       and all pages have text layers).

    Returns:
        Serialized exam dict, or None if skipped / failed.
    """
    path = Path(pdf_path)

    # Phase 1: Layout analysis
    layout = PaperLayoutEngine.process(path)

    # Optional early-skip for non-exam PDFs
    if skip_non_exam:
        total_image_blocks = sum(
            len([b for b in p.blocks if b.type == "image"])
            for p in layout.pages
        )
        if total_image_blocks == 0 and not any(p.is_scanned for p in layout.pages):
            logger.info("Skipping %s: all text-layer, no figures", path.name)
            return None

    logger.info(
        "%s: %d pages, is_scanned=%s — starting exam pipeline",
        path.name, layout.total_pages,
        any(p.is_scanned for p in layout.pages),
    )

    # Phase 2: Block-level OCR
    ocr_engine = BlockOCREngine(llm_client, path)
    try:
        pages_to_process = layout.pages[:min(len(layout.pages), max_pages)]
        page_contents = await ocr_engine.process_all_pages(
            PaperLayoutCacheWrapper(layout, pages_to_process),
            save_figures=save_figures,
        )
        ocr_blocks = sum(len(pc) for pc in page_contents)
        failed_blocks = sum(
            1 for pc in page_contents for bc in pc if bc.error
        )
        logger.info("Block OCR: %d blocks, %d failed", ocr_blocks, failed_blocks)
    finally:
        ocr_engine.close()

    # Phase 3: Structure into exam paper
    exam = ExamStructurer.structure(
        pages_to_process, page_contents, file_hash=layout.file_hash,
    )
    logger.info(
        "Structured: %s — subject=%s grade=%s type=%s questions=%d",
        path.name,
        exam.metadata.subject,
        exam.metadata.grade,
        exam.metadata.exam_type,
        len(exam.questions),
    )

    # Phase 4: Serialize
    return serialize_exam_paper(exam)


def serialize_exam_paper(exam: "ExamPaper") -> dict:
    """Serialize an ExamPaper to a plain dict (suitable for JSON)."""
    return {
        "paper_id": exam.paper_id,
        "raw_file_hash": exam.raw_file_hash,
        "total_pages": exam.total_pages,
        "metadata": {
            "subject": exam.metadata.subject,
            "grade": exam.metadata.grade,
            "exam_type": exam.metadata.exam_type,
            "year": exam.metadata.year,
            "total_score": exam.metadata.total_score,
            "duration_minutes": exam.metadata.duration_minutes,
        },
        "questions": [
            {
                "question_id": q.question_id,
                "index": q.index,
                "type": q.type,
                "content": q.content,
                "options": q.options,
                "answer": q.answer,
                "score": q.score,
                "page_num": q.page_num,
                "figures": [
                    {
                        "figure_id": f.figure_id,
                        "page_num": getattr(f, "page_num", 0),
                        "block_id": getattr(f, "block_id", 0),
                        "bbox": list(f.bbox),
                        "description": f.description,
                    }
                    for f in q.figures
                ],
            }
            for q in exam.questions
        ],
    }


def serialize_exam_paper_json(exam: "ExamPaper") -> str:
    """Serialize an ExamPaper to a JSON string."""
    return json_mod.dumps(serialize_exam_paper(exam), ensure_ascii=False, indent=2)


def write_exam_sidecar(pdf_path: Path, exam: "ExamPaper | dict") -> str | None:
    """Atomically write an ``.exam.json`` sidecar alongside the source PDF.

    Accepts either an ExamPaper object or a pre-serialized dict.
    Returns the path to the sidecar, or None on failure.
    """
    if isinstance(exam, dict):
        serialized = json_mod.dumps(exam, ensure_ascii=False, indent=2)
    else:
        serialized = serialize_exam_paper_json(exam)
    json_path = pdf_path.with_name(pdf_path.stem + ".exam.json")
    tmp_path = json_path.with_name(json_path.name + ".tmp")
    try:
        tmp_path.write_text(serialized, encoding="utf-8")
        os.replace(str(tmp_path), str(json_path))
        logger.info("Exam JSON sidecar: %s", json_path.name)
        return str(json_path)
    except OSError as exc:
        logger.error("Failed to write exam JSON for %s: %s", pdf_path.name, exc)
        return None


# ── Lightweight wrapper for process_all_pages compat ──────────────

class PaperLayoutCacheWrapper:
    """Wrap a PaperLayoutCache + filtered pages list for BlockOCREngine."""

    def __init__(self, layout_cache, pages):
        self.pages = pages
        self.file_hash = layout_cache.file_hash
        self.total_pages = layout_cache.total_pages
