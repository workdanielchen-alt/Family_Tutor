"""Run K12-optimized OCR pipeline."""
import sys, os, glob, asyncio, time, json
sys.path.insert(0, "/app")
from provider_api import _handle_pdf

# Clean checkpoints
for f in glob.glob("/data/chromadb/ocr_checkpoints/*.json"):
    try: os.remove(f)
    except: pass

async def r():
    t0 = time.time()
    content = await _handle_pdf(
        "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf",
        "k12-pipe",
        kb_name="初中任教版",
        filename="教材.pdf"
    )
    elapsed = time.time() - t0
    chars = len(content or "")
    print(f"Done: {elapsed:.1f}s, {chars} chars")
    with open("/tmp/k12_result.txt", "w") as f:
        f.write(content or "")

asyncio.run(r())
