#!/usr/bin/env python
"""Backfill figures from existing textbook PDFs into ChromaDB.

Scans all PDF files under the KB raw directory, calls
``extract_figures()`` from the shared extractors module, persists
PNGs and ChromaDB entries.

Usage::

    docker exec platform python /app/scripts/backfill_figures.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_figures")

KB_BASE_DIR = Path(os.environ.get("KB_BASE_DIR", "/data/knowledge_bases"))
KB_NAME = os.environ.get("KB_NAME", "初中教材")
SOURCES_DIR = Path(os.environ.get("SOURCES_DIR", "/data/sources"))


async def _process_one(pdf_path: Path, provider) -> int:
    """Process a single PDF: extract figures, persist, index."""
    fig_dir = pdf_path.parent / f"{pdf_path.stem}.figures"
    index_file = fig_dir / "_index.json"
    if fig_dir.is_dir() and index_file.is_file():
        existing = len([p for p in fig_dir.glob("*.png")])
        logger.info("  Already processed (%d figures), skipping", existing)
        return 0

    sys.path.insert(0, "/tutor_platform")
    from tutor_platform.rag.extractors import extract_figures

    t0 = time.time()
    figures = extract_figures(pdf_path, llm_client=None)
    extract_time = time.time() - t0
    if not figures:
        logger.info("  No figures extracted")
        return 0

    # Persist PNGs
    fig_dir.mkdir(exist_ok=True)
    for f in figures:
        img = f.pop("image_bytes", None)
        if img:
            fp = fig_dir / f"{f['figure_id']}.png"
            fp.write_bytes(img)
            f["image_path"] = str(fp)

    # ChromaDB
    t1 = time.time()
    result = await provider.add_figures(kb_name=KB_NAME, figures=figures)
    db_time = time.time() - t1
    added = result.get("count", 0)
    total_time = time.time() - t0
    logger.info(
        "  %d/%d figures → ChromaDB (extract=%.1fs db=%.1fs total=%.1fs)",
        added, len(figures), extract_time, db_time, total_time,
    )
    return added


async def main():
    # Locate PDFs
    raw_dirs = [
        KB_BASE_DIR / KB_NAME / "raw",
        KB_BASE_DIR / KB_NAME / "files",
    ]
    pdfs: list[Path] = []
    for d in raw_dirs:
        if d.is_dir():
            pdfs.extend(sorted(Path(d).glob("*.pdf")))
    if not pdfs:
        pdfs.extend(sorted(SOURCES_DIR.rglob("*.pdf")))
    if not pdfs:
        logger.warning("No PDFs found")
        return

    logger.info("Found %d PDFs for KB '%s'", len(pdfs), KB_NAME)

    sys.path.insert(0, "/tutor_platform")
    from tutor_platform.unified_provider import get_provider_instance

    provider = get_provider_instance()
    total = 0
    for i, pdf in enumerate(pdfs, 1):
        logger.info("[%d/%d] %s", i, len(pdfs), pdf.name)
        total += await _process_one(pdf, provider)

    logger.info("=== Done: %d figures added to ChromaDB ===", total)


if __name__ == "__main__":
    asyncio.run(main())
