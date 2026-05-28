"""
sync_kb_to_chromadb.py — Sync textbook KBs into ChromaDB.

Reads raw PDFs from data/knowledge_bases/<kb_name>/raw/, extracts text via
PyMuPDF, chunks, embeds via ChromaDB's built-in ONNX (all-MiniLM-L6-v2),
and adds to the "tutoring" collection.

Usage:
    docker exec platform python scripts/sync_kb_to_chromadb.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── config ──────────────────────────────────────────────────────────────────
KB_BASE_DIR = Path(os.getenv("KB_BASE_DIR", str(Path(__file__).resolve().parent.parent / "data" / "knowledge_bases")))
CHROMA_DIR = os.getenv("CHROMA_PERSIST_DIR", str(Path(KB_BASE_DIR).parent / "chromadb"))
CHUNK_SIZE = 512       # characters per chunk
CHUNK_OVERLAP = 64     # overlap
TARGET_COLLECTION = os.getenv("TARGET_COLLECTION", "tutoring")
KB_NAMES = ["初中数学教材", "初中物理教材", "初中化学教材"]

# On first use this downloads ~79 MB (all-MiniLM-L6-v2 ONNX model) and caches it.
# Subsequent calls are instant.
EMBED_FN = None


def _get_embed_fn():
    global EMBED_FN
    if EMBED_FN is None:
        from tutor_platform.tools.embeddings import RkllamaEmbeddingFunction
        EMBED_FN = RkllamaEmbeddingFunction()
        # Warm up — verify it works
        test = EMBED_FN(["warmup"])
        logger.info("Ollama embedding ready (dim=%d)", len(test[0]))
    return EMBED_FN


# ── text extraction ─────────────────────────────────────────────────────────
def extract_text_from_pdf(path: Path) -> str:
    """Extract text from a PDF using PyMuPDF."""
    try:
        import fitz
    except ImportError:
        logger.error("PyMuPDF not installed")
        sys.exit(1)

    pages: list[str] = []
    doc = fitz.open(path)
    for page in doc:
        text = page.get_text().strip()
        if text:
            pages.append(text)
    doc.close()
    if not pages:
        logger.warning("  No extractable text in %s (scanned PDF?)", path.name)
    return "\n\n".join(pages)


# ── chunking ────────────────────────────────────────────────────────────────
def chunk_text(text: str, source_label: str) -> list[dict]:
    """Split text into overlapping chunks."""
    if not text.strip():
        return []
    chunks: list[dict] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + CHUNK_SIZE, text_len)
        if end < text_len:
            boundary = max(
                text.rfind("。", start, end),
                text.rfind("\n", start, end),
                text.rfind(". ", start, end),
            )
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary + 1
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append({"text": chunk_text, "source": source_label})
        start = end - CHUNK_OVERLAP if end < text_len else text_len
    return chunks


# ── main ────────────────────────────────────────────────────────────────────
def sync_kb_to_chromadb():
    import chromadb
    from chromadb.config import Settings

    embed_fn = _get_embed_fn()

    os.makedirs(CHROMA_DIR, exist_ok=True)
    client = chromadb.PersistentClient(
        path=CHROMA_DIR,
        settings=Settings(anonymized_telemetry=False),
    )

    # Safety check: verify at least one KB has PDFs before deleting the collection.
    # Prevents accidentally dropping the collection when KB_BASE_DIR is wrong.
    found_pdfs = 0
    for kb_name in KB_NAMES:
        raw_dir = KB_BASE_DIR / kb_name / "raw"
        if raw_dir.is_dir():
            found_pdfs += len(list(raw_dir.glob("*.pdf")))
    if found_pdfs == 0:
        logger.error("No PDFs found in any KB directory — aborting! Check KB_BASE_DIR=%s", KB_BASE_DIR)
        return

    # Delete old collection if it exists (old nomic-embed-text embeddings)
    # so we recreate it with the new ONNX embedding function.
    try:
        client.delete_collection(TARGET_COLLECTION)
        logger.info("Deleted old '%s' collection (recreating with ONNX)", TARGET_COLLECTION)
    except Exception:
        pass  # First run or already deleted

    collection = client.create_collection(
        name=TARGET_COLLECTION,
        embedding_function=embed_fn,
    )
    logger.info("Created ChromaDB collection '%s' at %s", TARGET_COLLECTION, CHROMA_DIR)

    total_added = 0
    total_skipped = 0

    for kb_name in KB_NAMES:
        raw_dir = KB_BASE_DIR / kb_name / "raw"
        if not raw_dir.is_dir():
            logger.warning("Skipping %s: no raw/ directory", kb_name)
            continue

        pdfs = sorted(raw_dir.glob("*.pdf"))
        if not pdfs:
            logger.warning("Skipping %s: no PDFs", kb_name)
            continue
        logger.info("Processing %s (%d PDFs)", kb_name, len(pdfs))

        for pdf_path in pdfs:
            source_label = f"{kb_name}/{pdf_path.name}"

            # Skip if already synced (check by source metadata)
            try:
                existing = collection.get(where={"source": source_label}, limit=1)
                if existing["ids"]:
                    logger.info("  Already synced: %s", source_label)
                    total_skipped += 1
                    continue
            except Exception:
                pass

            logger.info("  Extracting: %s ...", pdf_path.name)
            full_text = extract_text_from_pdf(pdf_path)
            if not full_text:
                continue

            chunks = chunk_text(full_text, source_label)
            logger.info("  → %d chunks", len(chunks))

            # Process in batches
            batch_size = 10
            for batch_start in range(0, len(chunks), batch_size):
                batch = chunks[batch_start: batch_start + batch_size]
                texts = [c["text"] for c in batch]
                sources = [c["source"] for c in batch]
                chunk_ids = [f"{kb_name}_{pdf_path.stem}_{batch_start + i}" for i in range(len(texts))]

                try:
                    collection.add(
                        documents=texts,
                        ids=chunk_ids,
                        metadatas=[{"source": s, "kb": kb_name} for s in sources],
                    )
                    total_added += len(texts)
                except Exception as e:
                    logger.error("  Batch insert failed: %s", e)

                logger.info(
                    "  Batch %d/%d: +%d (total: %d)",
                    batch_start // batch_size + 1,
                    (len(chunks) + batch_size - 1) // batch_size,
                    len(texts),
                    total_added,
                )

    final_count = collection.count()
    logger.info(
        "Done! Added %d / skipped %d. Collection '%s' now has %d documents.",
        total_added, total_skipped, TARGET_COLLECTION, final_count,
    )


if __name__ == "__main__":
    print("=" * 60)
    print("  Sync textbook KBs → ChromaDB")
    print("=" * 60)
    print(f"  KB dir:    {KB_BASE_DIR}")
    print(f"  ChromaDB:  {CHROMA_DIR}")
    print(f"  Target:    {TARGET_COLLECTION}")
    print(f"  Batch:     {CHUNK_SIZE}c chunks, {CHUNK_OVERLAP}c overlap")
    print("=" * 60)
    sync_kb_to_chromadb()
