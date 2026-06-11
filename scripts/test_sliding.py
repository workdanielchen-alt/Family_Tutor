"""Test fixed-window sliding slice OCR."""
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
    print(f"Full: {W}x{H}", flush=True)

    WIN_H = 500
    OVERLAP = 150
    chunks = []
    start_y = 0
    while start_y < H:
        end_y = min(start_y + WIN_H, H)
        if end_y == H and H - start_y < WIN_H:
            start_y = max(0, H - WIN_H)
            end_y = H
        crop = img[start_y:end_y, 0:W]
        ch, cw = crop.shape[:2]
        if max(ch, cw) > 600:
            s = 600 / max(ch, cw)
            crop = cv2.resize(crop, (int(cw*s), int(ch*s)), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        chunks.append(buf.tobytes())
        if end_y == H:
            break
        start_y += WIN_H - OVERLAP

    print(f"Chunks: {len(chunks)}", flush=True)
    t0 = time.time()
    parts = []
    for idx, buf_data in enumerate(chunks):
        text = await _ocr_image_bytes(buf_data, f"win-{idx}")
        if text and text.strip():
            parts.append(text.strip())
            print(f"  Win {idx}: {len(text)} chars", flush=True)

    result = "\n".join(parts)
    elapsed = time.time() - t0
    print(f"\nTotal: {len(result)} chars in {elapsed:.1f}s", flush=True)
    print("---")
    print(result[:800])
    doc.close()

asyncio.run(main())
