"""Test qwen2vl with properly resized images (matching ocr_runner behavior)."""
import httpx
import base64
import cv2
import numpy as np
import fitz
import re

# Render page 1 at 200 DPI, then resize to max 1024px
doc = fitz.open("test_ocr_2pages.pdf")
for page_idx in range(2):
    zoom = 200 / 72
    pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    if max(h, w) > 1024:
        s = 1024 / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
    img_b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
    print(f"Page {page_idx+1}: {img.shape[1]}x{img.shape[0]}, {len(buf)} bytes")

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

    if r.status_code == 200:
        text = r.json()["choices"][0]["message"]["content"]
        print(f"\n=== Page {page_idx+1} OCR ({len(text)} chars) ===")
        print(text[:500])

        # Check garbled
        s = text.strip()
        cjk_count = sum(1 for c in s if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
        total_chars = len(s.replace(' ', '').replace('\n', ''))
        print(f"\nGarbled check: CJK={cjk_count}/{total_chars} = {cjk_count/max(total_chars,1)*100:.1f}%")
        coord_pairs = len(re.findall(r'\(\d+,\d+\)', s))
        print(f"Coordinate pairs: {coord_pairs}")
        if total_chars > 20 and cjk_count / max(total_chars, 1) < 0.03:
            print("→ GARBLED (low CJK ratio)")
        elif coord_pairs > 5 and coord_pairs * 5 > total_chars:
            print("→ GARBLED (too many coords)")
        else:
            print("→ OK")
    else:
        print(f"\n=== Page {page_idx+1} Error: {r.status_code} ===")
        print(r.text[:500])

doc.close()
