"""
Process chemistry textbook with Qwen2-VL OCR.
Tracks per-page timing, accuracy stats, and handles checkpoints.
"""
import sys, os, time, json, hashlib, logging
sys.path.insert(0, "/app")
import asyncio
import fitz
from provider_api import _ocr_image_bytes, _handle_pdf
from tutor_platform.tools.preprocess import preprocess_image_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("textbook-ocr")

REPORT_FILE = "/tmp/textbook_ocr_report.json"
PDF_PATH = "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf"
KB_NAME = "初中任教版"
TRACE_ID = "textbook-batch-001"


async def check_progress():
    ckpt_dir = "/data/chromadb/ocr_checkpoints"
    filename = os.path.basename(PDF_PATH)
    ckpt_key = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]
    ckpt_path = os.path.join(ckpt_dir, f"{ckpt_key}.json")
    if os.path.isfile(ckpt_path):
        with open(ckpt_path) as f:
            data = json.load(f)
        done = len(data.get("page_texts", {}))
        total = data.get("total_pages", 121)
        return done, total
    return 0, 121


async def run():
    log.info("=" * 60)
    log.info("Starting chemistry textbook OCR")
    log.info(f"PDF: {PDF_PATH}")
    log.info("=" * 60)

    t0 = time.time()
    content = await _handle_pdf(PDF_PATH, TRACE_ID, kb_name=KB_NAME, filename=os.path.basename(PDF_PATH))
    elapsed = time.time() - t0

    if not content:
        log.error("OCR produced no content!")
        return

    # Build stats from checkpoint data
    done, total = await check_progress()
    stats = {
        "filename": os.path.basename(PDF_PATH),
        "total_pages": total,
        "pages_done": done,
        "total_chars": len(content),
        "total_time_s": round(elapsed, 1),
        "avg_time_per_page_s": round(elapsed / total, 1) if total else 0,
        "chars_per_page": round(len(content) / total, 0) if total else 0,
        "completed_at": time.time(),
    }

    log.info("=" * 60)
    log.info(f"OCR COMPLETE")
    log.info(f"  Pages: {done}/{total}")
    log.info(f"  Total chars: {stats['total_chars']}")
    log.info(f"  Total time: {stats['total_time_s']}s ({stats['total_time_s']/60:.1f} min)")
    log.info(f"  Avg: {stats['avg_time_per_page_s']}s/page")
    log.info(f"  Chars/page: {stats['chars_per_page']}")
    log.info("=" * 60)

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    with open("/tmp/textbook_ocr_full.txt", "w", encoding="utf-8") as f:
        f.write(content)
    log.info(f"Full text saved to /tmp/textbook_ocr_full.txt")


if __name__ == "__main__":
    asyncio.run(run())
