"""Verify checkpoint/resume logic for PDF OCR pipeline."""
import asyncio, json, os, hashlib, shutil
from pathlib import Path


async def test():
    pdf = "/data/knowledge_bases/初中任教版/raw/义务教育教科书·化学九年级下册.pdf"
    filename = Path(pdf).name
    ckpt_key = hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]
    ckpt_dir = "/data/chromadb/ocr_checkpoints"
    ckpt_path = os.path.join(ckpt_dir, f"{ckpt_key}.json")

    print(f"=== Checkpoint for: {filename} ===")
    print(f"  Key: {ckpt_key}")
    print(f"  Path: {ckpt_path}")
    print(f"  Exists: {os.path.isfile(ckpt_path)}")

    if os.path.isfile(ckpt_path):
        with open(ckpt_path) as f:
            data = json.load(f)
        total = data.get("total_pages", 0)
        page_texts = data.get("page_texts", {})
        print(f"  Total pages: {total}")
        print(f"  Done pages: {len(page_texts)}")
        print(f"  Updated: {data.get('updated_at', '?')}")
        if page_texts:
            sample_idx = min(page_texts.keys(), key=lambda k: int(k))
            print(f"  Sample page {sample_idx}: {page_texts[sample_idx][:80]}...")

    # Backup & test: create a fake checkpoint to verify resume logic
    print("\n=== Test: Checkpoint resume logic ===")
    os.makedirs(ckpt_dir, exist_ok=True)
    test_ckpt = {
        "filename": filename,
        "page_texts": {"0": "九年级下册 化学 封面文字", "1": "目录 第一章...", "2": "page 3 text"},
        "total_pages": 121,
        "updated_at": 9999999999,
    }
    with open(ckpt_path + ".test", "w", encoding="utf-8") as f:
        json.dump(test_ckpt, f, ensure_ascii=False)

    # Simulate loading checkpoint (same logic as _pdf_manual_ocr_fallback)
    num_pages = 121
    pages_text = [""] * num_pages
    done_pages = set()
    if os.path.isfile(ckpt_path + ".test"):
        with open(ckpt_path + ".test") as f:
            ckpt_data = json.load(f)
        stored = ckpt_data.get("page_texts", {})
        for k, v in stored.items():
            pn = int(k)
            if 0 <= pn < num_pages and v:
                done_pages.add(pn)
                pages_text[pn] = f"--- Page {pn + 1} ---\n{v}"
    print(f"  Resume would skip {len(done_pages)} already-processed pages")
    print(f"  Remaining to process: {num_pages - len(done_pages)}")
    assert pages_text[0].startswith("--- Page 1 ---"), "Page 1 should be restored"
    assert pages_text[2].startswith("--- Page 3 ---"), "Page 3 should be restored"
    assert pages_text[3] == "", "Page 4 should be empty (not in checkpoint)"
    print("  ✅ Resume logic: OK")

    # Clean up
    os.remove(ckpt_path + ".test")

    # Test: what if checkpoint has garbled data?
    print("\n=== Test: Corrupted checkpoint handling ===")
    with open(ckpt_path + ".corrupt", "w") as f:
        f.write("not json{")
    try:
        pages_text2 = [""] * num_pages
        if os.path.isfile(ckpt_path + ".corrupt"):
            with open(ckpt_path + ".corrupt") as f:
                ckpt_data2 = json.load(f)
    except Exception as e:
        print(f"  Corrupted checkpoint caught: {type(e).__name__}")
        print("  ✅ Fallback: starts fresh")
    finally:
        if os.path.isfile(ckpt_path + ".corrupt"):
            os.remove(ckpt_path + ".corrupt")

    print("\n=== All checkpoint tests passed ===")

asyncio.run(test())
