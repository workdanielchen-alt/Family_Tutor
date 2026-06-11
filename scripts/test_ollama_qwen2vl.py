"""Test Ollama qwen2-vl:2b vision capability."""
import httpx, asyncio, base64
from PIL import Image, ImageDraw, ImageFont
import io


async def test():
    # Create test image with text
    img = Image.new("RGB", (500, 150), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except (OSError, IOError):
        font = ImageFont.load_default()
    draw.text((30, 50), "Hello OCR 化学测试", fill="black", font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    print("=== Test 1: Simple image ===")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("http://ollama:11434/api/chat", json={
            "model": "qwen2-vl:2b",
            "messages": [
                {"role": "user", "content": "Transcribe all text from this image:", "images": [img_b64]}
            ],
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=30)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        content = r.json()["message"]["content"]
        print(f"  OCR ({len(content)} chars): {content[:300]}")
    elif r.status_code == 400:
        print(f"  400: {r.text[:200]}")

    # Test with real textbook page
    print("\n=== Test 2: Chemistry textbook page (72 DPI) ===")
    import fitz
    doc = fitz.open("/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf")
    page = doc[14]  # page 15
    pix = page.get_pixmap(dpi=100)
    img_b64_pdf = base64.b64encode(pix.tobytes("png")).decode("utf-8")
    print(f"  Image: {len(img_b64_pdf)//1024}KB base64, {pix.width}x{pix.height}")

    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("http://ollama:11434/api/chat", json={
            "model": "qwen2-vl:2b",
            "messages": [
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64_pdf}"}},
                    {"type": "text", "text": "Transcribe ALL text from this image exactly as written. Output only the text."}
                ]}
            ],
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=120)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        content = r.json()["message"]["content"]
        print(f"  OCR ({len(content)} chars):")
        print(f"    {content[:500]}")

    doc.close()


asyncio.run(test())
