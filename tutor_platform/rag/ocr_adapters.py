"""OCR adapters for pymupdf4llm — plug MiniCPM-V into the hybrid OCR pipeline.

pymupdf4llm's ``to_markdown(use_ocr=True, ocr_function=...)`` auto-detects which
pages/regions need OCR (no text layer, garbled characters, character-like vectors,
images containing text) and calls ``ocr_function(pixmap) -> str`` for only those
regions.  This gives us:

  * Layout analysis + reading-order reconstruction (from pymupdf4llm)
  * Table detection + GFM output (from pymupdf4llm)
  * Heading hierarchy from font sizes (from pymupdf4llm)
  * Selective OCR (only regions that actually need it → ~50% fewer calls)
  * Seamless merge of OCR'd and native text into one Markdown

We provide a ``MinicpmOCRFunc`` callable that wraps the existing Ollama MiniCPM-V /
rkllama NPU OCR infrastructure.

Usage::

    from tutor_platform.rag.ocr_adapters import get_minicpm_ocr_function

    md = pymupdf4llm.to_markdown(
        "scanned.pdf",
        use_ocr=True,
        ocr_function=get_minicpm_ocr_function(trace_id="my-task"),
    )

No Tesseract required — OCR runs through the same Ollama / rkllama endpoints that
the rest of the platform already uses.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz

logger = logging.getLogger(__name__)

# Reuse the same semaphore pattern as provider_api for NPU OOM prevention.
_ocr_semaphore = asyncio.Semaphore(2)


def _run_async(coro):
    """Run an async coroutine from sync code without an existing event loop.

    Called from inside ``pymupdf4llm.to_markdown()`` which is sync.  We're
    typically invoked from a thread-pool executor (``run_in_executor``), so
    ``asyncio.run()`` creates a fresh event loop without conflict.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # If there IS a running loop (unlikely from pymupdf4llm's call path),
    # delegate to a thread to avoid nested-loop issues.
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _ocr_pixmap_bytes(image_bytes: bytes, trace_id: str = "") -> str:
    """OCR raw image bytes via Ollama MiniCPM-V → rkllama NPU fallback.

    Preprocessing (OpenCV deskew / denoise / CLAHE) is applied before OCR.
    Garbled output is treated as OCR failure (empty string).
    """
    from tutor_platform.tools.preprocess import preprocess_image_bytes

    # Preprocess
    try:
        processed = preprocess_image_bytes(image_bytes)
    except Exception as exc:
        logger.warning("[%s] OCR preprocess failed: %s, using raw bytes", trace_id, exc)
        processed = image_bytes

    img_b64 = base64.b64encode(processed).decode("utf-8")

    # ── Route: Ollama (env OCR_PROVIDER=ollama) → rkllama (default) ──
    provider = os.getenv("OCR_PROVIDER", "rkllama")
    async with _ocr_semaphore:
        text = ""
        if provider == "ollama":
            text = await _ocr_via_ollama(img_b64, trace_id)
        else:
            text = await _ocr_via_rkllama(img_b64, trace_id)

    # Garbled detection
    if text and _is_garbled(text):
        logger.warning("[%s] OCR output garbled (%d chars), treating as failure", trace_id, len(text))
        return ""
    return text


async def _ocr_via_ollama(img_b64: str, trace_id: str) -> str:
    """OCR via Ollama /api/chat (MiniCPM-V 4.6)."""
    import httpx

    ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
    model = os.getenv("OLLAMA_OCR_MODEL", "openbmb/minicpm-v4.6:q4_K_M")
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "15m")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是一个专业OCR文字识别引擎。\n\n"
                                "规则：\n"
                                "1. 只输出图片中实际存在的文字——不要添加任何描述、解释或额外内容\n"
                                "2. 中文文字直接输出纯文本（不要加$分隔符）\n"
                                "3. 数学公式用$LaTeX$行内或$$display$$块级\n"
                                "4. 保留原始换行和段落结构\n"
                                "5. 如果没有文字，返回空字符串"
                            ),
                        },
                        {
                            "role": "user",
                            "content": "识别这张图片中的所有文字，只输出文字本身：",
                            "images": [img_b64],
                        },
                    ],
                    "stream": False,
                    "keep_alive": keep_alive,
                    "options": {"temperature": 0},
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                content = (data.get("message", {}).get("content", "") or "").strip()
                # Strip common MiniCPM explanation prefixes
                import re
                m = re.search(r'[一-鿿]|\$\$?|\\\\\[', content)
                if m:
                    content = content[m.start():]
                else:
                    content = re.sub(
                        r'^[\s\n]*(?:图片[中的上].*?[：:]|'
                        r'识别结果[：:]|OCR[识别结果]*[：:]|'
                        r'the (?:ocr|text|image).*?[：:])',
                        '',
                        content,
                        flags=re.IGNORECASE,
                    )
                content = re.sub(r'^[\s\n：:，,;.、]+', '', content).strip()
                return content
            logger.warning("[%s] Ollama OCR returned HTTP %s", trace_id, resp.status_code)
    except Exception as exc:
        logger.warning("[%s] Ollama OCR request failed: %s", trace_id, exc)
    return ""


async def _ocr_via_rkllama(img_b64: str, trace_id: str) -> str:
    """OCR via rkllama NPU /v1/ocr endpoint."""
    import httpx

    rkllama_url = os.getenv("RKLLAMA_URL", "http://rkllama:8080")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{rkllama_url}/v1/ocr",
                json={
                    "image": img_b64,
                    "language": "zh",
                    "return_formulas": False,
                    "return_layout": False,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return (data.get("text", "") or "").strip()
            logger.warning("[%s] rkllama OCR returned HTTP %s", trace_id, resp.status_code)
    except Exception as exc:
        logger.warning("[%s] rkllama OCR request failed: %s", trace_id, exc)
    return ""


def _is_garbled(text: str) -> bool:
    """Heuristic: detect likely garbled OCR output.

    Returns True when the text contains an abnormally high ratio of
    replacement characters or non-printable runs.
    """
    if not text:
        return False
    # Too many replacement chars (U+FFFD)
    if text.count("\ufffd") > max(10, len(text) * 0.1):
        return True
    # Long runs of non-CJK, non-ASCII, non-printable
    if len(text) > 20:
        printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
        if printable / len(text) < 0.5:
            return True
    return False


# ── Public adapter class ────────────────────────────────────────────

class MinicpmOCRFunc:
    """pymupdf4llm-compatible OCR callable wrapping MiniCPM-V / rkllama.

    Implements the ``ocr_function`` protocol::

        ocr_fn = MinicpmOCRFunc(trace_id="my-task")
        md = pymupdf4llm.to_markdown(
            "scanned.pdf", use_ocr=True, ocr_function=ocr_fn,
        )

    pymupdf4llm passes a ``fitz.Pixmap`` for each region that needs OCR.
    We convert it to PNG bytes, preprocess with OpenCV, and route to the
    configured OCR backend (Ollama MiniCPM-V or rkllama NPU).
    """

    __slots__ = ("trace_id",)

    def __init__(self, trace_id: str = "") -> None:
        self.trace_id = trace_id

    def __call__(self, obj, **kwargs) -> str:
        """OCR a page/pixmap → plain text string.

        pymupdf4llm v1.27+ passes a ``fitz.Page``; older versions pass
        a ``fitz.Pixmap``.  We handle both: Page → render to Pixmap →
        PNG bytes → OCR.

        Accepts ``**kwargs`` for forward-compatibility (pymupdf4llm
        may pass ``dpi``, ``page_number``, etc.).
        """
        try:
            # pymupdf4llm v1.27+ passes a fitz.Page
            if hasattr(obj, 'get_pixmap'):
                dpi_val = kwargs.get('dpi', 200)
                pixmap = obj.get_pixmap(dpi=dpi_val)
            elif hasattr(obj, 'tobytes'):
                pixmap = obj
            else:
                logger.warning("[%s] Unknown OCR object type: %s", self.trace_id, type(obj))
                return ""

            png_bytes = pixmap.tobytes("png")
        except Exception as exc:
            logger.warning("[%s] pixmap render failed: %s", self.trace_id, exc)
            return ""

        if len(png_bytes) < 100:
            return ""

        result = _run_async(_ocr_pixmap_bytes(png_bytes, self.trace_id))
        if result:
            logger.info("[%s] OCR returned %d chars", self.trace_id, len(result))
        else:
            logger.warning("[%s] OCR returned empty for %d bytes", self.trace_id, len(png_bytes))
        return result


def get_minicpm_ocr_function(trace_id: str = "") -> MinicpmOCRFunc:
    """Factory returning a callable for pymupdf4llm's ``ocr_function`` parameter.

    ``trace_id`` is attached to all log entries for correlation.
    """
    return MinicpmOCRFunc(trace_id=trace_id)
