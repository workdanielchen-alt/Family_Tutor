"""Standalone OCR runner - exports PDF pages then OCRs them."""
import os, sys, base64, json, time, hashlib
import urllib.request
import fitz

API_URL = "http://qwen2vl:8081/v1/chat/completions"
PDF_PATH = "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf"
OUTPUT_DIR = "/tmp/textbook_pages"
CHECKPOINT_DIR = "/tmp/ocr_checkpoints"
MAX_EDGE = 600


def export_pages():
    """Export PDF pages as JPEG images (200 DPI, 600px max edge)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    doc = fitz.open(PDF_PATH)
    total = len(doc)
    print(f"Exporting {total} pages...")
    for i in range(total):
        out = os.path.join(OUTPUT_DIR, f"page_{i+1:03d}.jpg")
        if os.path.isfile(out):
            continue
        pix = doc[i].get_pixmap(dpi=200)
        # Resize if needed
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        w, h = img.size
        if max(w, h) > MAX_EDGE:
            scale = MAX_EDGE / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        img.save(out, "JPEG", quality=85)
        if (i+1) % 20 == 0:
            print(f"  {i+1}/{total}")
    doc.close()
    print(f"Done. {total} pages in {OUTPUT_DIR}")


def process_page(img_path):
    """OCR a single page image."""
    with open(img_path, "rb") as f:
        img_data = f.read()
    img_b64 = base64.b64encode(img_data).decode("utf-8")

    payload = {
        "model": "qwen2-vl",
        "messages": [
            {"role": "system", "content": "你是一个精通理科教材的OCR专家。请精准提取图片中的所有中文和化学方程式。化学方程式请使用标准的文本或LaTeX格式表达（如2H2+O2=2H2O）。不要输出任何坐标框，不要废话，直接输出识别结果。"},
            {"role": "user", "content": [
                {"type": "text", "text": "请提取本页教材的全部内容："},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
            ]}
        ],
        "temperature": 0.1,
        "max_tokens": 1024
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        text = result["choices"][0]["message"]["content"]
        return {"status": "ok", "text": text, "chars": len(text)}
    except Exception as e:
        return {"status": "error", "text": "", "chars": 0, "reason": str(e)}


def run():
    export_pages()

    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    pages = sorted(os.listdir(OUTPUT_DIR))

    # Load checkpoint
    done = set()
    ckpt_file = os.path.join(CHECKPOINT_DIR, "progress.json")
    if os.path.isfile(ckpt_file):
        with open(ckpt_file) as f:
            done = set(json.load(f).get("done", []))
        print(f"Resuming from checkpoint: {len(done)} pages done")

    total = len(pages)
    t0 = time.time()

    for idx, page in enumerate(pages):
        page_num = page.replace("page_", "").replace(".jpg", "")
        if page_num in done:
            continue

        path = os.path.join(OUTPUT_DIR, page)
        for attempt in range(3):
            result = process_page(path)
            if result["status"] == "ok":
                break
            print(f"  Retry {attempt+1} {page}: {result.get('reason','')[:60]}")
            time.sleep(2)

        done.add(page_num)

        # Save incremental checkpoint
        with open(ckpt_file, "w") as f:
            json.dump({"done": list(done), "total": total}, f)

        elapsed = time.time() - t0
        rate = (idx + 1) / (elapsed / 60) if elapsed > 0 else 0
        eta = (total - idx - 1) / rate if rate > 0 else 0
        chars = result.get("chars", 0)
        status = "OK" if result["status"] == "ok" else "FAIL"
        print(f"[{idx+1}/{total}] {page} {status} {chars}c {elapsed/60:.1f}min ETA:{eta:.0f}min")

    print(f"\nDone. {total} pages in {elapsed/60:.1f} min")

if __name__ == "__main__":
    run()
