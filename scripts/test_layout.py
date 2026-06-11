"""Test contour-based layout analysis OCR."""
import sys, time, cv2, numpy as np, fitz, asyncio
sys.path.insert(0, "/app")
from provider_api import _ocr_image_bytes

async def main():
    doc = fitz.open("/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf")
    page = doc[14]
    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    H, W = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 10))
    dilated = cv2.dilate(thresh, kernel, iterations=3)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blocks = []
    for cnt in contours:
        _, y, _, h = cv2.boundingRect(cnt)
        if h > H * 0.02:
            blocks.append((y, h))
    blocks.sort(key=lambda x: x[0])
    merged = []
    for y, h in blocks:
        if merged and y < merged[-1][0] + merged[-1][1]:
            py, ph = merged.pop()
            merged.append((py, max(y + h - py, ph)))
        else:
            merged.append((y, h))

    print(f"Blocks: {len(merged)}", flush=True)
    t0 = time.time()
    parts = []
    for idx, (y, h) in enumerate(merged):
        crop = img[y:y+h, :]
        ch, cw = crop.shape[:2]
        if max(ch, cw) > 600:
            s = 600 / max(ch, cw)
            crop = cv2.resize(crop, (int(cw*s), int(ch*s)), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        text = await _ocr_image_bytes(buf.tobytes(), f"layout-{idx}")
        if text and text.strip():
            parts.append(text.strip())
            print(f"  Block {idx}: {len(text)} chars", flush=True)

    result = "\n".join(parts)
    elapsed = time.time() - t0
    print(f"\nTotal: {len(result)} chars in {elapsed:.1f}s", flush=True)
    print("---")
    print(result[:600])
    doc.close()

asyncio.run(main())
