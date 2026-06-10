"""OCR runner: call qwen2vl llama-server API with timeout + auto-recovery."""
import asyncio, base64, hashlib, json, logging, os, time
from pathlib import Path

logger = logging.getLogger(__name__)
_ocr_semaphore = asyncio.Semaphore(2)  # 2 页并行，匹配 server -np 2

QWEN_URL = os.getenv("QWEN2VL_URL", "http://qwen2vl:8081")

SYSTEM_PROMPT = (
    "你是一个专业的OCR文字提取引擎。你的唯一任务是精准复制图片中的所有文字内容。\n\n"
    "【硬性规则】\n"
    "1. 只输出图片中实际存在的文字，不添加任何解释、评论或补充\n"
    "2. 保持原文的段落结构和换行\n"
    "3. 数学公式用 LaTeX 格式：行内公式用 $...$，独立公式用 $$...$$\n"
    "4. 化学方程式用文本格式：2H2 + O2 = 2H2O\n"
    "5. 中文和标点保持原样\n"
    "6. 如果某个字无法辨认，用 [？] 标记，不要猜测\n"
    "7. 禁止输出坐标、位置信息、图片描述等 OCR 无关内容"
)
USER_PROMPT = "OCR提取以下图片的全部文字内容，保持原文格式："
RETRY_PROMPT = "重新OCR：只输出纯文字，不要任何坐标或位置信息："

# ── Formula → LaTeX prompt (crop pipeline) ──
FORMULA_SYSTEM_PROMPT = (
    "你是一个数学公式识别助手。请直接将图片中的数学/化学公式翻译为标准的 LaTeX 格式。\n\n"
    "【硬性规则】\n"
    "1. 只输出 LaTeX，不添加任何解释、寒暄或 Markdown 代码块标签\n"
    "2. 化学方程式用文本 LaTeX：$2H_2 + O_2 \\rightarrow 2H_2O$\n"
    "3. 数学公式用 $...$（行内）或 $$...$$（块级）包裹\n"
    "4. 如果图片中没有公式，返回空字符串\n"
    "5. 禁止输出坐标、位置信息"
)
FORMULA_USER_PROMPT = "将图片中的公式翻译为 LaTeX："


async def _ocr_page_qwen_formula(img_b64: str, trace_id: str) -> str:
    """Send a formula crop to Qwen2-VL → return LaTeX (max 256 tokens, 60s timeout)."""
    import httpx, re as _re

    try:
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(
                f"{QWEN_URL}/v1/chat/completions",
                json={
                    "model": "qwen2-vl",
                    "messages": [
                        {"role": "system", "content": FORMULA_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                                },
                                {"type": "text", "text": FORMULA_USER_PROMPT},
                            ],
                        },
                    ],
                    "max_tokens": 256,
                    "temperature": 0.0,
                },
            )
            if r.status_code == 200:
                text = r.json()["choices"][0]["message"]["content"].strip()
                text = _re.sub(r"\(\d+,\d+\)", "", text)
                text = _re.sub(r"\n{3,}", "\n\n", text).strip()
                if text:
                    logger.info("[%s] Qwen2-VL formula → LaTeX: %d chars", trace_id, len(text))
                return text
            logger.warning("[%s] Qwen2-VL formula HTTP %s", trace_id, r.status_code)
    except Exception as e:
        logger.warning("[%s] Qwen2-VL formula error: %s", trace_id, e)
    return ""


async def _qwen_health() -> bool:
    import httpx
    try:
        r = await httpx.AsyncClient(timeout=5).get(f"{QWEN_URL}/health")
        return r.status_code == 200
    except Exception:
        return False


async def _ocr_page_qwen(img_b64: str, trace_id: str, attempt: int) -> str:
    """Call qwen2vl llama-server API. 300s timeout. Returns text or ''."""
    import httpx, re as _re
    prompt = RETRY_PROMPT if attempt > 0 else USER_PROMPT
    timeout = 300 if attempt == 0 else 180

    async with _ocr_semaphore:
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{QWEN_URL}/v1/chat/completions", json={
                    "model": "qwen2-vl",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                            {"type": "text", "text": prompt},
                        ]}
                    ],
                    "max_tokens": 1536, "temperature": 0.0,  # OCR 必须确定性输出
                })
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"].strip()
                    text = _re.sub(r"\(\d+,\d+\)", "", text)
                    text = _re.sub("\n{3,}", "\n\n", text).strip()
                    if text:
                        logger.info("[%s] Qwen2-VL OCR returned %d chars", trace_id, len(text))
                    return text
                logger.warning("[%s] Qwen2-VL HTTP %s", trace_id, r.status_code)
        except Exception as e:
            logger.warning("[%s] Qwen2-VL error: %s", trace_id, e)
    return ""


def _is_garbled(text: str) -> bool:
    """检测 OCR 结果是否为乱码。
    启发式规则：
    - 空或过短
    - 中文字符占比低于 5%（说明可能输出的是坐标数字或英文乱码）
    - 纯数字/坐标格式（括号内数字对过多）
    """
    s = text.strip()
    if not s or len(s) < 10:
        return True
    # 统计中文字符
    cjk_count = sum(1 for c in s if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    total_chars = len(s.replace(' ', '').replace('\n', ''))
    # 如果有效字符中中文占比过低，可能是乱码
    if total_chars > 20 and cjk_count / max(total_chars, 1) < 0.03:
        return True
    # 大量坐标对 (xx,yy) 说明模型在输出定位信息
    coord_pairs = len(__import__('re').findall(r'\(\d+,\d+\)', s))
    if coord_pairs > 5 and coord_pairs * 5 > total_chars:
        return True
    return False


async def _ocr_one_page(page_idx: int, doc, trace_id: str) -> str:
    """OCR one page — RapidOCR (fast) with Qwen2-VL formula crop fallback.

    Architecture:
      1. Render page at 200 DPI → keep high-res original.
      2. Downscale to 600px → RapidOCR (fast, ~2-3s).
      3. No formulas → return RapidOCR text immediately.
      4. Formulas detected → crop formula regions from 200 DPI original,
         send each crop to Qwen2-VL for LaTeX translation, stitch back.
    """
    import cv2, numpy as np, fitz, asyncio, tempfile

    try:
        zoom = 200 / 72
        pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        nparr = np.frombuffer(pix.tobytes("png"), np.uint8)
        img_200dpi = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_200dpi is None:
            return ""
        h_hi, w_hi = img_200dpi.shape[:2]

        # 600px version for RapidOCR detection
        if max(h_hi, w_hi) > 600:
            scale = 600 / max(h_hi, w_hi)
            img_600 = cv2.resize(
                img_200dpi,
                (int(w_hi * scale), int(h_hi * scale)),
                interpolation=cv2.INTER_AREA,
            )
        else:
            img_600 = img_200dpi

        _, buf = cv2.imencode(".jpg", img_600, [cv2.IMWRITE_JPEG_QUALITY, 85])

        # ── Fast path: RapidOCR on 600px ──
        try:
            from tutor_platform.rag.rapid_ocr import (
                ocr_image_bytes as _rapid_ocr,
                has_formula,
                crop_formula_regions,
                merge_formula_lines,
            )

            loop = asyncio.get_running_loop()
            text, boxes = await loop.run_in_executor(
                None, _rapid_ocr, buf.tobytes()
            )

            if text and not has_formula(text):
                logger.debug(
                    "[%s] Page %d RapidOCR: %d chars, %d lines",
                    trace_id, page_idx + 1, len(text), len(boxes),
                )
                return f"--- Page {page_idx + 1} ---\n{text.strip()}"

        except ImportError:
            logger.debug("rapid_ocr not in PYTHONPATH, using Qwen2-VL full-page path")
            text = ""
            boxes = []
        except Exception as exc:
            logger.warning("[%s] RapidOCR fast path failed: %s", trace_id, exc)
            text = ""
            boxes = []

        if not boxes:
            # No boxes → fall back to full-page Qwen
            _, buf_png = cv2.imencode(".png", img_600, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            for attempt in range(2):
                result = await _ocr_page_qwen(
                    base64.b64encode(buf_png.tobytes()).decode("utf-8"),
                    trace_id, attempt,
                )
                if result and not _is_garbled(result):
                    return f"--- Page {page_idx + 1} ---\n{result.strip()}"
                if attempt == 0 and not result and not await _qwen_health():
                    break
            if text:
                _merged = "\n".join(merge_formula_lines(text.split("\n")))
                _annotated = (
                    "【AI注意】以下内容由OCR识别，化学式下标可能丢失，请根据化学常识推断。\n\n"
                    + _merged
                )
                return f"--- Page {page_idx + 1} ---\n{_annotated.strip()}"
            return ""

        # ── Crop pipeline: formula regions from 200 DPI original ──
        # Scale factors: RapidOCR coords (600px) → 200 DPI coords
        scale_y = h_hi / img_600.shape[0]
        scale_x = w_hi / img_600.shape[1]

        crops = await loop.run_in_executor(
            None, crop_formula_regions, img_200dpi, boxes, scale_x, scale_y,
        )

        if not crops:
            logger.info(
                "[%s] Page %d no formula crops, using RapidOCR text (%d chars)",
                trace_id, page_idx + 1, len(text) if text else 0,
            )
            return f"--- Page {page_idx + 1} ---\n{text.strip()}" if text else ""

        logger.info(
            "[%s] Page %d %d formula crops → Qwen2-VL",
            trace_id, page_idx + 1, len(crops),
        )

        # Send each crop to Qwen2-VL with formula→LaTeX prompt
        formula_texts: list[str] = []
        for i, crop_bytes in enumerate(crops):
            img_b64 = base64.b64encode(crop_bytes).decode("utf-8")
            crop_result = await _ocr_page_qwen_formula(img_b64, trace_id)
            if crop_result:
                formula_texts.append(crop_result)
                logger.debug(
                    "[%s] Page %d crop %d/%d: %d chars",
                    trace_id, page_idx + 1, i + 1, len(crops), len(crop_result),
                )
            else:
                logger.warning(
                    "[%s] Page %d crop %d/%d: Qwen failed",
                    trace_id, page_idx + 1, i + 1, len(crops),
                )

        # Stitch: replace formula lines in RapidOCR text with Qwen LaTeX
        if formula_texts:
            stitched = text + "\n\n[公式]\n" + "\n".join(formula_texts)
            logger.info(
                "[%s] Page %d crops done: %d formula regions, %d chars total",
                trace_id, page_idx + 1, len(formula_texts), len(stitched),
            )
            return f"--- Page {page_idx + 1} ---\n{stitched.strip()}"
        else:
            # Qwen failed, use RapidOCR with formula annotations
            _merged = "\n".join(merge_formula_lines(text.split("\n")))
            _annotated = (
                "【AI注意】以下内容由OCR识别，化学式下标可能丢失"
                "（如H2→H₂, CuSO4→CuSO₄），请根据化学常识推断。\n\n"
                + _merged
            )
            return f"--- Page {page_idx + 1} ---\n{_annotated.strip()}"

    except Exception as exc:
        logger.warning("[%s] Page %d OCR failed: %s", trace_id, page_idx + 1, exc)
        return ""


def _save_checkpoint(ckpt_path, pages_text, num_pages, filename=""):
    _pt = {}
    for i in range(num_pages):
        if pages_text[i]:
            hdr = f"--- Page {i+1} ---\n"
            _raw = pages_text[i][len(hdr):] if pages_text[i].startswith(hdr) else pages_text[i]
            _pt[str(i)] = _raw
    try:
        os.makedirs(os.path.dirname(ckpt_path), exist_ok=True)
        with open(ckpt_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"page_texts": _pt, "total_pages": num_pages,
                       "updated_at": time.time()}, f, ensure_ascii=False)
        os.replace(ckpt_path + ".tmp", ckpt_path)
    except Exception as e:
        logger.warning("Checkpoint save failed: %s", e)


async def run_pdf_ocr(file_path: str, trace_id: str, filename: str = "") -> str:
    """OCR via qwen2vl API. Sliding window 2 concurrent pages, checkpoint resume."""
    try:
        import fitz
    except ImportError:
        return ""

    try:
        doc = fitz.open(file_path)
    except Exception:
        return ""

    num_pages = min(len(doc), 200)
    pages_text = [""] * num_pages

    ckpt_dir = os.path.join(os.environ.get("CHROMA_PERSIST_DIR", "/data/chromadb"), "ocr_checkpoints")
    ckpt_key = hashlib.sha256((filename or Path(file_path).name).encode("utf-8")).hexdigest()[:16]
    ckpt_path = os.path.join(ckpt_dir, f"{ckpt_key}.json")
    done_pages = set()
    if os.path.isfile(ckpt_path):
        try:
            data = json.load(open(ckpt_path, encoding="utf-8"))
            for k, v in data.get("page_texts", {}).items():
                pn = int(k)
                if 0 <= pn < num_pages and v:
                    done_pages.add(pn)
                    pages_text[pn] = f"--- Page {pn + 1} ---\n{v}"
            if done_pages:
                logger.info("[%s] Resume: %d/%d pages", trace_id, len(done_pages), num_pages)
        except Exception as e:
            logger.warning("[%s] Checkpoint load failed: %s", trace_id, e)

    # Sliding window: 2 concurrent pages
    in_flight: dict = {}
    next_start = 0

    def start_next():
        nonlocal next_start
        while next_start < num_pages:
            if next_start not in done_pages and next_start not in in_flight:
                t = asyncio.create_task(_ocr_one_page(next_start, doc, trace_id))
                in_flight[next_start] = t
                next_start += 1
                return True
            next_start += 1
        return False

    for _ in range(2):
        start_next()

    while in_flight:
        done, _ = await asyncio.wait(in_flight.values(), return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            page_idx = next(i for i, task in in_flight.items() if task is t)
            text = t.result()
            del in_flight[page_idx]
            if text:
                pages_text[page_idx] = text
                logger.info("[%s] Page %d OK (%d chars)", trace_id, page_idx + 1, len(text))
            else:
                logger.warning("[%s] Page %d failed", trace_id, page_idx + 1)
            _save_checkpoint(ckpt_path, pages_text, num_pages, filename)
            start_next()

    doc.close()
    result = "\n\n".join(t for t in pages_text if t)
    logger.info("[%s] OCR done: %d/%d pages, %d chars", trace_id,
                len([t for t in pages_text if t]), num_pages, len(result))
    return result
