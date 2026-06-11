"""Test clean full-page 600px OCR."""
import sys, time, cv2, numpy as np, fitz, asyncio
sys.path.insert(0, "/app")
from provider_api import _ocr_image_bytes

async def main():
    doc = fitz.open("/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf")
    page = doc[14]
    zoom = 200 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    if max(h, w) > 600:
        s = 600 / max(h, w)
        img = cv2.resize(img, (int(w*s), int(h*s)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

    t0 = time.time()
    text = await _ocr_image_bytes(buf.tobytes(), "final-test")
    elapsed = time.time() - t0
    print(f"Time: {elapsed:.1f}s")
    print(f"OCR: {len(text or '')} chars")
    if text: print(text[:500])
    doc.close()

asyncio.run(main())
