"""Simple OCR runner - calls API endpoint, no provider_api import."""
import httpx, asyncio, os, sys

async def run():
    pdf = "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf"
    kb_name = "初中任教版"
    url = "http://localhost:8100/api/kb/ingest-file"

    with open(pdf, "rb") as f:
        files = {"file": ("教材.pdf", f, "application/pdf")}
        async with httpx.AsyncClient(timeout=7200) as c:
            r = await c.post(url, data={"kb_name": kb_name}, files=files, timeout=7200)

    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"OK: {data.get('route', '?')}, content={len(data.get('content',''))} chars")
    else:
        print(f"Error: {r.text[:300]}")

asyncio.run(run())
