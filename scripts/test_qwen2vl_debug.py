"""Test OCR with proper context size."""
import fitz, asyncio, httpx, base64

async def test():
    doc = fitz.open("/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf")

    for pg, dpi in [(14, 72), (14, 100), (5, 72)]:
        page = doc[pg]
        pix = page.get_pixmap(dpi=dpi)
        img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        print(f"=== Page {pg+1} @ {dpi}DPI ({pix.width}x{pix.height}) ===")

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post("http://qwen2vl:8081/v1/chat/completions", json={
                "model": "qwen2-vl",
                "messages": [
                    {"role": "system", "content": "你是一个精准的OCR教学助手。请直接将图片中的中文字符全部按顺序提取出来，不要输出坐标。"},
                    {"role": "user", "content": [
                        {"type": "text", "text": "请文字识别（OCR）这张教材页中的所有中文内容："},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    ]}
                ],
                "max_tokens": 2048, "temperature": 0,
            }, timeout=120)

        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            txt = r.json()["choices"][0]["message"]["content"]
            print(f"OCR ({len(txt)} chars):")
            print(txt[:500] if txt else "(empty)")
        else:
            print(f"Error: {r.text[:200]}")
        print()

    doc.close()

asyncio.run(test())
