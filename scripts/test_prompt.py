"""Test different OCR prompts with qwen2vl."""
import httpx, base64, time
import cv2, numpy as np, fitz

doc = fitz.open("test_ocr_2pages.pdf")
zoom = 72 / 72  # 72 DPI = 1x
pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
h, w = img.shape[:2]
if max(h, w) > 800:
    s = 800 / max(h, w)
    img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
_, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
doc.close()

print(f"Image: {img.shape[1]}x{img.shape[0]}, {len(buf)} bytes")

prompts = [
    # Prompt 1: Very direct, from ocr_runner
    {
        "system": "你是一个专业的OCR文字提取引擎。你的唯一任务是精准复制图片中的所有文字内容。\n【硬性规则】\n1. 只输出图片中实际存在的文字，不添加任何解释、评论或补充\n2. 保持原文的段落结构和换行\n3. 禁止输出坐标、位置信息、图片描述等 OCR 无关内容\n4. 中文和标点保持原样",
        "user": "OCR提取以下图片的全部文字内容，保持原文格式：",
    },
    # Prompt 2: Even simpler
    {
        "system": "只输出图片中的文字，不要输出任何其他内容。不要输出坐标。",
        "user": "文字：",
    },
    # Prompt 3: Empty system
    {
        "system": "",
        "user": "Read all Chinese text in this image. Output ONLY the text, no coordinates or descriptions:",
    },
]

for i, p in enumerate(prompts):
    msgs = []
    if p["system"].strip():
        msgs.append({"role": "system", "content": p["system"]})
    msgs.append({
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": p["user"]},
        ]
    })

    t0 = time.time()
    r = httpx.post(
        "http://localhost:8082/v1/chat/completions",
        json={"model": "qwen2-vl", "messages": msgs, "max_tokens": 1500, "temperature": 0},
        timeout=300,
    )
    elapsed = time.time() - t0

    if r.status_code == 200:
        text = r.json()["choices"][0]["message"]["content"].strip()
        print(f"\n=== Prompt {i+1} ({elapsed:.1f}s, {len(text)} chars) ===")
        print(text[:300])
    else:
        print(f"\n=== Prompt {i+1} Error ({elapsed:.1f}s): {r.status_code} ===")
        print(r.text[:200])
