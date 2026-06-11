"""Quiet OCR progress monitor - reads checkpoint only, no API calls."""
import hashlib, json, os, time

key = hashlib.sha256("义务教育教科书·化学九年级下册.pdf".encode()).hexdigest()[:16]
ckpt = f"/data/chromadb/ocr_checkpoints/{key}.json"
start = time.time()
last_done = 0

while True:
    if os.path.isfile(ckpt):
        try:
            with open(ckpt) as f:
                d = json.load(f)
            done = len(d.get("page_texts", {}))
            total = d.get("total_pages", 121)
            if done != last_done:
                elapsed = time.time() - start
                rate = done / (elapsed / 3600) if elapsed > 0 else 0
                eta_h = (total - done) / rate if rate > 0 else 0
                print(f"[{time.strftime('%H:%M:%S')}] {done}/{total} | "
                      f"{elapsed/60:.0f}m elapsed | {rate:.1f} pg/h | ETA {eta_h:.1f}h")
                last_done = done
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    time.sleep(30)
