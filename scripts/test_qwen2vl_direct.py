"""Test qwen2vl API directly to see what OCR output looks like."""
import httpx
import base64
import fitz

# Render page 1 of the test PDF as image
doc = fitz.open("test_ocr_2pages.pdf")
page = doc[0]
pix = page.get_pixmap(dpi=200)
img_bytes = pix.tobytes("png")
img_b64 = base64.b64encode(img_bytes).decode("utf-8")
print(f"Image: {pix.width}x{pix.height}, {len(img_bytes)} bytes")
doc.close()

# Call qwen2vl
r = httpx.post(
    "http://localhost:8082/v1/chat/completions",
    json={
        "model": "qwen2-vl",
        "messages": [
            {
                "role": "system",
                "content": "你是一个精通理科教材的OCR专家。请精准提取图片中的所有中文和化学方程式。化学方程式请使用标准的文本或LaTeX格式表达（如2H2+O2=2H2O）。不要输出任何坐标框，不要废话，直接输出识别结果。"
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": "请提取本页教材的全部内容："},
                ]
            }
        ],
        "max_tokens": 1500,
        "temperature": 0.1,
    },
    timeout=120,
)

data = r.json()
if r.status_code == 200:
    text = data["choices"][0]["message"]["content"]
    print(f"\n=== OCR Output ({len(text)} chars) ===")
    print(text)

    # Check garbled detection
    import re
    s = text.strip()
    print(f"\n=== Garbled Check ===")
    print(f"Length: {len(s)}")
    cjk_count = sum(1 for c in s if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    total_chars = len(s.replace(' ', '').replace('\n', ''))
    print(f"Total non-space chars: {total_chars}")
    print(f"CJK chars: {cjk_count}")
    if total_chars > 20 and cjk_count / max(total_chars, 1) < 0.03:
        print("→ GJK ratio too low: GARBLED!")
    else:
        print(f"→ CJK ratio: {cjk_count/max(total_chars, 1)*100:.1f}% - OK")

    coord_pairs = len(re.findall(r'\(\d+,\d+\)', s))
    print(f"Coordinate pairs: {coord_pairs}")
    if coord_pairs > 5 and coord_pairs * 5 > total_chars:
        print("→ Too many coordinates: GARBLED!")
else:
    print(f"Error: {r.status_code}")
    print(data)
