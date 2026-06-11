"""End-to-end test: process a chemistry textbook page via OCR pipeline."""
import asyncio
from docker.platform.provider_api import _ocr_image_bytes, _handle_pdf


async def test():
    pdf = "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf"
    trace_id = "e2e-test"

    print("=== Testing _handle_pdf (full pipeline) ===")
    content = await _handle_pdf(pdf, trace_id)
    if content:
        print(f"Extracted {len(content)} chars")
        print(content[:500])
    else:
        print("Empty result")

    print("\n=== Done ===")

asyncio.run(test())
