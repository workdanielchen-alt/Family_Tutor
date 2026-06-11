"""Test qwen2vl with image - try with minimal image first."""
import httpx, base64, io, time
from PIL import Image, ImageDraw

# Create a tiny image with text
img = Image.new("RGB", (100, 50), "white")
d = ImageDraw.Draw(img)
d.text((5, 15), "ABC", fill="black")
buf = io.BytesIO()
img.save(buf, "PNG")
img_bytes = buf.getvalue()
b64 = base64.b64encode(img_bytes).decode()

print(f"Image: {len(img_bytes)} bytes")

# First try the local API
t0 = time.time()
r = httpx.post(
    "http://localhost:8082/v1/chat/completions",
    json={
        "model": "qwen2-vl",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": "Output text:"},
        ]}],
        "max_tokens": 50,
        "temperature": 0,
    },
    timeout=60,
)
elapsed = time.time() - t0
print(f"Local: {r.status_code} ({elapsed:.1f}s)")
if r.status_code == 200:
    print(f"Response: {r.json()['choices'][0]['message']['content']}")
else:
    print(f"Error: {r.text[:500]}")

# Now try the system prompt version used by OCR runner
print("\n--- Testing with OCR system prompt ---")
t0 = time.time()
r = httpx.post(
    "http://localhost:8082/v1/chat/completions",
    json={
        "model": "qwen2-vl",
        "messages": [
            {"role": "system", "content": "OCR expert. Extract all text from images accurately."},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "Extract text from this image:"},
            ]}
        ],
        "max_tokens": 50,
        "temperature": 0,
    },
    timeout=60,
)
elapsed = time.time() - t0
print(f"Local: {r.status_code} ({elapsed:.1f}s)")
if r.status_code == 200:
    print(f"Response: {r.json()['choices'][0]['message']['content']}")
else:
    print(f"Error: {r.text[:500]}")
