"""Clean stale OCR checkpoint and kill old process."""
import hashlib, json, os, signal

# Clean checkpoint
key = hashlib.sha256("义务教育教科书·化学九年级下册.pdf".encode()).hexdigest()[:16]
p = f"/data/chromadb/ocr_checkpoints/{key}.json"
if os.path.isfile(p):
    with open(p) as f:
        d = json.load(f)
    done = len(d.get("page_texts", {}))
    total = d.get("total_pages", 121)
    os.remove(p)
    print(f"Cleaned checkpoint: {done}/{total} pages")
else:
    print("No checkpoint to clean")
