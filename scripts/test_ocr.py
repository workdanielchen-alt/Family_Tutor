import httpx, asyncio, json, time, base64, io

async def test():
    # Check health
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get("http://localhost:8082/health")
        print(f"Health: {r.status_code} {r.text}")

    # Simple text test
    t0 = time.time()
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("http://localhost:8082/v1/chat/completions", json={
            "model": "qwen2-vl",
            "messages": [{"role": "user", "content": "回复一个字：好"}],
            "max_tokens": 5,
            "temperature": 0.0,
        })
        elapsed = time.time() - t0
        data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content", "")
        finish = choice.get("finish_reason", "")
        print(f"Response: '{content}' finish={finish} time={elapsed:.1f}s")
        usage = data.get("usage", {})
        if usage:
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            print(f"Usage: prompt={pt} completion={ct}")

    # Now test with a generated image
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (600, 400), "white")
    draw = ImageDraw.Draw(img)
    lines = [
        "第三章 一元二次方程",
        "3.1 定义：ax2+bx+c=0",
        "例题：解 x2-5x+6=0",
        "解：(x-2)(x-3)=0",
        "x1=2, x2=3",
    ]
    y = 20
    for line in lines:
        draw.text((20, y), line, fill="black")
        y += 30

    buf = io.BytesIO()
    img.save(buf, "PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("http://localhost:8082/v1/chat/completions", json={
            "model": "qwen2-vl",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": "OCR提取图片中的所有文字，保持格式："},
                ]
            }],
            "max_tokens": 300,
            "temperature": 0.0,
        })
        elapsed = time.time() - t0
        data = r.json()
        if "error" in data:
            print(f"OCR ERROR: {data['error']}")
            return
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        content = msg.get("content", "")
        finish = choice.get("finish_reason", "")
        print(f"OCR time={elapsed:.1f}s finish={finish} output_len={len(content)}")
        print(f"---OCR OUTPUT---")
        print(content)
        usage = data.get("usage", {})
        if usage:
            print(f"Usage: {json.dumps(usage)}")

asyncio.run(test())
