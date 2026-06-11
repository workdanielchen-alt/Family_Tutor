"""Upload test PDF to platform API and wait for OCR result."""
import httpx, sys, time, json

PDF_PATH = "test_ocr_2pages.pdf"
KB_NAME = "初中教材"
LEARNER_ID = "test-ocr-v2"  # fresh learner to avoid cache hit
API_URL = "http://localhost:8100/api/kb/ingest-file"

# Upload the file
print(f"Uploading {PDF_PATH} to KB '{KB_NAME}'...")
t0 = time.time()

with open(PDF_PATH, "rb") as f:
    r = httpx.post(
        API_URL,
        data={"kb_name": KB_NAME, "learner_id": LEARNER_ID},
        files={"file": ("test_ocr_2pages.pdf", f, "application/pdf")},
        timeout=300,
    )

elapsed = time.time() - t0
print(f"Response time: {elapsed:.1f}s")
print(f"Status: {r.status_code}")

if r.status_code == 200:
    data = r.json()
    content_len = data.get("content_len", 0)
    route = data.get("route", "")
    dt_synced = data.get("dt_synced", False)
    print(f"Content length: {content_len}")
    print(f"Route: {route}")
    print(f"DT synced: {dt_synced}")
    content = data.get("content", "")
    if content:
        print(f"\n--- Extracted content ({len(content)} chars) ---")
        print(content[:1000])
        if len(content) > 1000:
            print(f"... ({len(content) - 1000} more chars)")
    print(f"\nFull response: {json.dumps(data, ensure_ascii=False, indent=2)[:2000]}")
else:
    print(f"Error: {r.text[:1000]}")
