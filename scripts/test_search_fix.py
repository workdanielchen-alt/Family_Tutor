"""Test KB search after sanitization fix."""
import asyncio
from tutor_platform.unified_provider import get_provider_instance, _sanitize_collection_name

print("Name sanitization:")
print(f"  初中教材 -> {_sanitize_collection_name('初中教材')}")
print(f"  curriculum -> {_sanitize_collection_name('curriculum')}")
print(f"  kb_Zu4F3wD-a-s -> {_sanitize_collection_name('kb_Zu4F3wD-a-s')}")

async def test():
    p = get_provider_instance()
    queries = ["勾股定理", "一元二次方程", "二次函数", "力的合成", "English"]
    for q in queries:
        r = await p.query("初中教材", [q], n_results=2)
        texts = [x.get("content", "")[:80] for x in r if x.get("content")]
        print(f"\n'{q}': {len(r)} results")
        for t in texts:
            print(f"  -> {t}...")

asyncio.run(test())
