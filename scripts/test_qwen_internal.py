"""Test qwen2vl from inside Docker network via platform container."""
import httpx
import base64
import asyncio
import sys

sys.path.insert(0, "/app")


async def main():
    """Call qwen2vl via platform's internal network."""
    # Create a simple test image
    from PIL import Image, ImageDraw
    import io

    img = Image.new("RGB", (200, 100), "white")
    d = ImageDraw.Draw(img)
    d.text((10, 30), "Test OCR", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    print(f"Calling http://qwen2vl:8081/v1/chat/completions...")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("http://qwen2vl:8081/v1/chat/completions", json={
            "model": "qwen2-vl",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "Output the text in the image:"},
            ]}],
            "max_tokens": 100,
            "temperature": 0,
        })
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            text = r.json()["choices"][0]["message"]["content"]
            print(f"Response ({len(text)}c): {text}")
        else:
            print(f"Error: {r.text[:500]}")

    # Now test with a full page image
    print("\n--- Testing full page ---")
    import fitz
    import cv2
    import numpy as np

    doc = fitz.open("/tmp/tmp*.pdf" if len(sys.argv) > 1 else "/tmp/tmps92ngn3x.pdf")
    # Find PDF in /tmp
    import glob
    pdfs = glob.glob("/tmp/tmp*.pdf")
    if pdfs:
        doc = fitz.open(pdfs[0])
        page = doc[0]
        zoom = 200 / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        if max(h, w) > 1024:
            s = 1024 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
        print(f"Image: {img.shape[1]}x{img.shape[0]}, {len(buf)} bytes")
        doc.close()

        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post("http://qwen2vl:8081/v1/chat/completions", json={
                "model": "qwen2-vl",
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个精通理科教材的OCR专家。请精准提取图片中的所有中文和化学方程式。不要输出任何坐标框，直接输出识别结果。"
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                            {"type": "text", "text": "请提取本页教材的全部内容："},
                        ]
                    }
                ],
                "max_tokens": 1500,
                "temperature": 0.1,
            })
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                text = r.json()["choices"][0]["message"]["content"]
                print(f"Response ({len(text)} chars):")
                print(text[:1000])

                # Check garbled
                import re as _re
                s = text.strip()
                cjk_count = sum(1 for c in s if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
                total_chars = len(s.replace(' ', '').replace('\n', ''))
                print(f"\nCJK: {cjk_count}/{total_chars} = {cjk_count/max(total_chars,1)*100:.1f}%")
                coord_pairs = len(_re.findall(r'\(\d+,\d+\)', s))
                print(f"Coords: {coord_pairs}")
            else:
                print(f"Error: {r.text[:500]}")


asyncio.run(main())
