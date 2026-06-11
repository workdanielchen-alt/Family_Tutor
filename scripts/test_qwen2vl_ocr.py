"""Test qwen2vl with different prompts and params to debug text output."""
import fitz, asyncio, httpx, base64

async def test():
    doc = fitz.open("/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf")
    page = doc[14]

    # Try different DPIs and prompts
    for dpi in [100, 72]:
        pix = page.get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        print(f"\n=== {dpi}DPI ({pix.width}x{pix.height}) ===")

        prompts = [
            # Very direct OCR instruction
            "OCR the image. Output every Chinese character you see, no coordinates.",
            # Force text extraction
            "Write the exact text content of this page, character by character.",
            # Minimal prompt to avoid triggering detection mode
            "Text:",
        ]

        for pi, text in enumerate(prompts):
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post("http://qwen2vl:8081/v1/chat/completions", json={
                    "model": "qwen2-vl",
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": text},
                    ]}],
                    "max_tokens": 2048, "temperature": 0,
                }, timeout=120)
            txt = ""
            if r.status_code == 200:
                txt = r.json()["choices"][0]["message"]["content"]
            print(f"  P{pi+1}: {r.status_code} ({len(txt)}c) {txt[:100]}")
    doc.close()

asyncio.run(test())
