"""Run _handle_pdf and save result."""
import sys
sys.path.insert(0, "/app")
import asyncio
from provider_api import _handle_pdf

async def r():
    content = await _handle_pdf(
        "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf",
        "final-run",
        kb_name="初中任教版",
        filename="教材.pdf"
    )
    with open("/tmp/ocr_final.txt", "w") as f:
        f.write(content or "")
    print(f"Done: {len(content or '')} chars")

asyncio.run(r())
