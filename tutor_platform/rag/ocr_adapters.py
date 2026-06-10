"""OCR adapters for pymupdf4llm — plug multimodal VL models into the hybrid OCR pipeline.

pymupdf4llm's ``to_markdown(use_ocr=True, ocr_function=...)`` auto-detects which
pages/regions need OCR (no text layer, garbled characters, character-like vectors,
images containing text) and calls ``ocr_function(pixmap) -> str`` for only those
regions.  This gives us:

  * Layout analysis + reading-order reconstruction (from pymupdf4llm)
  * Table detection + GFM output (from pymupdf4llm)
  * Heading hierarchy from font sizes (from pymupdf4llm)
  * Selective OCR (only regions that actually need it → ~50% fewer calls)
  * Seamless merge of OCR'd and native text into one Markdown

We provide a ``MinicpmOCRFunc`` callable that wraps the multimodal VL OCR
infrastructure (Qwen2-VL / rkllama NPU).

Usage::

    from tutor_platform.rag.ocr_adapters import get_minicpm_ocr_function

    md = pymupdf4llm.to_markdown(
        "scanned.pdf",
        use_ocr=True,
        ocr_function=get_minicpm_ocr_function(trace_id="my-task"),
    )

No Tesseract required — OCR runs through the same Qwen2-VL / rkllama endpoints that
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
    """OCR raw image bytes — RapidOCR (fast) with Qwen2-VL formula crop fallback.

    1. RapidOCR (PP-OCRv4, ~2-3s) for plain-text pages.
    2. If formulas are detected, crop formula regions and send to Qwen2-VL.
    3. No formulas → return RapidOCR text immediately.

    Preprocessing (OpenCV resize/encode) is applied before OCR.
    Garbled output is treated as OCR failure (empty string).
    """
    import asyncio, cv2, numpy as np
    from tutor_platform.tools.preprocess import preprocess_image_bytes

    # Preprocess
    try:
        processed = preprocess_image_bytes(image_bytes)
    except Exception as exc:
        logger.warning("[%s] OCR preprocess failed: %s, using raw bytes", trace_id, exc)
        processed = image_bytes

    # ── Fast path: RapidOCR ──
    try:
        from tutor_platform.rag.rapid_ocr import (
            ocr_image_bytes as _rapid_ocr,
            has_formula,
            crop_formula_regions,
            merge_formula_lines,
        )

        loop = asyncio.get_running_loop()
        text, boxes = await loop.run_in_executor(None, _rapid_ocr, processed)
        if text and not has_formula(text):
            logger.info(
                "[%s] RapidOCR fast path: %d chars, %d lines",
                trace_id, len(text), len(boxes),
            )
            return text

        if text and boxes:
            # ── Formula crops from preprocessed (600px) image ──
            nparr = np.frombuffer(processed, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                crops = await loop.run_in_executor(
                    None,
                    crop_formula_regions,
                    img,
                    boxes,
                    1.0,  # scale_x
                    1.0,  # scale_y (already 600px)
                )
                if crops:
                    logger.info(
                        "[%s] Formula detected, %d crops → Qwen2-VL",
                        trace_id, len(crops),
                    )
                    try:
                        from ocr_runner import _ocr_page_qwen_formula
                    except ImportError:
                        _ocr_page_qwen_formula = None

                    if _ocr_page_qwen_formula is not None:
                        formula_texts: list[str] = []
                        for crop_bytes in crops:
                            img_b64 = base64.b64encode(crop_bytes).decode("utf-8")
                            crop_res = await _ocr_page_qwen_formula(img_b64, trace_id)
                            if crop_res:
                                formula_texts.append(crop_res)

                        if formula_texts:
                            stitched = text + "\n\n[公式]\n" + "\n".join(formula_texts)
                            return stitched

            # Fall through to RapidOCR text if crop/Qwen failed → merge formula lines
            _merged = "\n".join(merge_formula_lines(text.split("\n")))
            _annotated = (
                "【AI注意】以下内容由OCR识别，化学式下标可能丢失"
                "（如H2→H₂, CuSO4→CuSO₄），请根据化学常识推断，并以原始图片为准。\n\n"
                + _merged
            )
            logger.info(
                "[%s] Formula crops failed, using RapidOCR text (%d chars) with annotations",
                trace_id, len(_annotated),
            )
            return _annotated

        if text:
            logger.info(
                "[%s] Formula detected, falling back to Qwen2-VL (%d chars)",
                trace_id, len(text),
            )
    except ImportError:
        logger.debug("[%s] rapid_ocr not available, using Qwen2-VL path", trace_id)
    except Exception as exc:
        logger.warning("[%s] RapidOCR fast path failed: %s", trace_id, exc)

    # ── Fallback: Qwen2-VL / rkllama full-image (no crops available) ──
    img_b64 = base64.b64encode(processed).decode("utf-8")
    provider = os.getenv("OCR_PROVIDER", "rkllama")
    async with _ocr_semaphore:
        text = ""
        if provider == "qwen2vl":
            text = await _ocr_via_qwen2vl(img_b64, trace_id)
        else:
            text = await _ocr_via_rkllama(img_b64, trace_id)

    # Garbled detection
    if text and _is_garbled(text):
        logger.warning("[%s] OCR output garbled (%d chars), treating as failure", trace_id, len(text))
        return ""
    return text


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


async def _ocr_via_qwen2vl(img_b64: str, trace_id: str) -> str:
    """OCR via Qwen2-VL-2B (llama.cpp server, /v1/chat/completions).

    Image already preprocessed (600px max) by preprocess_image_bytes upstream.
    """
    import httpx

    qwen_url = os.getenv("QWEN2VL_URL", "http://qwen2vl:8081")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{qwen_url}/v1/chat/completions",
                json={
                    "model": "qwen2-vl",
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个精通理科教材的OCR专家。请精准提取图片中的所有中文和化学方程式。化学方程式请使用标准的文本或LaTeX格式表达（如2H2+O2=2H2O）。不要输出任何坐标框，不要废话，直接输出识别结果。"
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                                },
                                {
                                    "type": "text",
                                    "text": "请提取本页教材的全部内容：",
                                },
                            ],
                        }
                    ],
                    "max_tokens": 1500,
                    "temperature": 0.1,
                },
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "").strip()
                if text:
                    import re as _re
                    text = _re.sub(r'\(\d+,\d+\),?\(?\d*\,?\d*\)?', '', text)
                    text = _re.sub(r'\n{3,}', '\n\n', text).strip()
                    logger.info("[%s] Qwen2-VL OCR returned %d chars", trace_id, len(text))
                return text
            logger.warning("[%s] Qwen2-VL OCR returned HTTP %s", trace_id, resp.status_code)
    except Exception as exc:
        logger.warning("[%s] Qwen2-VL OCR request failed: %s", trace_id, exc)
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
    """pymupdf4llm-compatible OCR callable wrapping Qwen2-VL / rkllama.

    Implements the ``ocr_function`` protocol::

        ocr_fn = MinicpmOCRFunc(trace_id="my-task")
        md = pymupdf4llm.to_markdown(
            "scanned.pdf", use_ocr=True, ocr_function=ocr_fn,
        )

    pymupdf4llm passes a ``fitz.Pixmap`` for each region that needs OCR.
    We convert it to PNG bytes, preprocess with OpenCV, and route to the
    configured OCR backend (Qwen2-VL / rkllama NPU).
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
