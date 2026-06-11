import httpx, asyncio, json, time, base64, io
from PIL import Image, ImageDraw

async def main():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("http://localhost:8082/health")
        print(f"Health: {r.status_code}")
        s = await c.get("http://localhost:8082/slots")
        slots = s.json()
        for sl in slots:
            print(f"Slot {sl['id']}: n_ctx={sl['n_ctx']}")

    img = Image.new("RGB", (600, 300), "white")
    draw = ImageDraw.Draw(img)
    lines = ["一元二次方程 ax2+bx+c=0", "解: x2-5x+6=0", "(x-2)(x-3)=0, x=2或x=3"]
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 30), line, fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    t0 = time.time()
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post("http://localhost:8082/v1/chat/completions", json={
            "model": "qwen2-vl",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": "OCR提取以上图片文字:"},
            ]}],
            "max_tokens": 200,
            "temperature": 0.0,
        })
        data = r.json()
        elapsed = time.time() - t0
        if "error" in data:
            print(f"ERROR: {data['error']}")
            return
        content = data["choices"][0]["message"]["content"]
        print(f"Time: {elapsed:.1f}s")
        print(f"Output ({len(content)} chars):")
        print(content)

asyncio.run(main())
