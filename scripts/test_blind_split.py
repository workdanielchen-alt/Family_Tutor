"""Test blind-split OCR on one page."""
import sys, time, cv2, numpy as np, fitz, asyncio
sys.path.insert(0, "/app")
from provider_api import _ocr_image_bytes

async def main():
    pdf = "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf"
    doc = fitz.open(pdf)
    page = doc[14]

    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    print(f"Full page: {w}x{h}", flush=True)

    # Blind split via horizontal projection
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 230, 255, cv2.THRESH_BINARY_INV)
    proj = np.sum(thresh, axis=1)
    gap_thresh = w * 0.02
    in_gap = proj < gap_thresh

    segments = []
    seg_start = 0
    in_text = False
    for row in range(h):
        if in_gap[row] and not in_text:
            continue
        if not in_gap[row] and not in_text:
            seg_start = row
            in_text = True
        elif in_gap[row] and in_text:
            if row - seg_start > 20:
                segments.append((seg_start, row))
            in_text = False
    if in_text and h - seg_start > 20:
        segments.append((seg_start, h))
    if not segments:
        segments.append((0, h))

    print(f"Segments: {len(segments)}", flush=True)

    t0 = time.time()
    seg_texts = []
    for idx, (y0, y1) in enumerate(segments):
        crop = img[y0:y1, :]
        ch, cw = crop.shape[:2]
        if max(ch, cw) > 600:
            s = 600 / max(ch, cw)
            crop = cv2.resize(crop, (int(cw*s), int(ch*s)), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        seg_text = await _ocr_image_bytes(buf.tobytes(), f"seg-{idx}")
        if seg_text and seg_text.strip():
            seg_texts.append(seg_text.strip())
            print(f"  Seg {idx}: {len(seg_text)} chars", flush=True)

    elapsed = time.time() - t0
    result = "\n\n".join(seg_texts)
    print(f"\nTotal: {len(result)} chars in {elapsed:.1f}s", flush=True)
    print("---")
    print(result[:500])
    doc.close()

asyncio.run(main())
