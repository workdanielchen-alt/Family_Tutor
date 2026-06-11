"""Test qwen2vl with a very long timeout to see if image processing eventually completes."""
import httpx, base64, io, time, sys
from PIL import Image, ImageDraw

# Create a small test image
img = Image.new("RGB", (300, 150), "white")
d = ImageDraw.Draw(img)
d.text((10, 50), "测试文字OCR识别", fill="black")
img_bytes = io.BytesIO()
img.save(img_bytes, "PNG")
img_data = img_bytes.getvalue()
b64 = base64.b64encode(img_data).decode()

print(f"Image: {len(img_data)} bytes ({300}x150)")

t0 = time.time()
print(f"Sending request (timeout=300s)...")
try:
    r = httpx.post(
        "http://localhost:8082/v1/chat/completions",
        json={
            "model": "qwen2-vl",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "输出图中文字："},
            ]}],
            "max_tokens": 100,
            "temperature": 0,
        },
        timeout=300,
    )
    elapsed = time.time() - t0
    print(f"Status: {r.status_code} ({elapsed:.1f}s)")
    if r.status_code == 200:
        text = r.json()["choices"][0]["message"]["content"]
        print(f"Response ({len(text)}c): {text}")
    else:
        print(f"Error: {r.text[:500]}")
except Exception as e:
    elapsed = time.time() - t0
    print(f"Exception after {elapsed:.1f}s: {e}")
