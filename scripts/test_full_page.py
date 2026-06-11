"""Test qwen2vl with a full page resized like the OCR runner."""
import httpx, base64, time
import cv2, numpy as np, fitz

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
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
    print(f"Page {page_idx+1}: {img.shape[1]}x{img.shape[0]}, {len(buf)} bytes")

    t0 = time.time()
    r = httpx.post(
        "http://localhost:8082/v1/chat/completions",
        json={
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
        },
        timeout=300,
    )
    elapsed = time.time() - t0
    print(f"  Status: {r.status_code} ({elapsed:.1f}s)")

    if r.status_code == 200:
        text = r.json()["choices"][0]["message"]["content"].strip()
        print(f"  Output ({len(text)} chars):")
        print(text[:500])
    else:
        print(f"  Error: {r.text[:300]}")

doc.close()
