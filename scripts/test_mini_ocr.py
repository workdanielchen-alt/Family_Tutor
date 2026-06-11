"""Test qwen2vl with minimal image to check basic functionality."""
import httpx, base64, io
from PIL import Image, ImageDraw

img = Image.new("RGB", (200, 100), "white")
d = ImageDraw.Draw(img)
d.text((10, 30), "Hello OCR World", fill="black")
buf = io.BytesIO()
img.save(buf, "PNG")
b64 = base64.b64encode(buf.getvalue()).decode()

r = httpx.post("http://localhost:8082/v1/chat/completions", json={
    "model": "qwen2-vl",
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        {"type": "text", "text": "Output the text in the image:"},
    ]}],
    "max_tokens": 100, "temperature": 0,
}, timeout=60)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    print(f"Response ({len(text)}c): {text}")
else:
    print(f"Error: {r.text[:500]}")
