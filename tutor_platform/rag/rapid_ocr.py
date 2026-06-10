"""RapidOCR adapter — PP-OCRv4 via ONNX Runtime for Chinese textbook OCR.

Provides a synchronous OCR entry point that replaces Qwen2-VL for plain-text
pages.  When formula / equation patterns are detected in the output, the
caller can fall back to Qwen2-VL for those specific regions.

Usage::

    from tutor_platform.rag.rapid_ocr import ocr_image_bytes

    text, boxes = ocr_image_bytes(image_bytes)
    if has_formula(text):
        # crop formula regions → Qwen2-VL
        ...
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Singleton engine (loads models once, ~2.5s cold start) ──
_ENGINE = None


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        import time

        t0 = time.time()
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
        logger.info("RapidOCR engine loaded (%.1fs)", time.time() - t0)
    return _ENGINE


# ── Core OCR ──────────────────────────────────────────────────────


def ocr_image_bytes(image_bytes: bytes) -> tuple[str, list]:
    """OCR image bytes → plain text + per-line bounding boxes.

    Returns:
        text:  concatenated text, one line per detected region.
        boxes: list of **(ymin, ymax, text, confidence, bbox_4pt)** for
               each detected text region.
    """
    import tempfile

    # RapidOCR accepts file paths natively; bytes path is fragile.
    # Write to a temp PNG so the OpenCV decode path is reliable.
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        engine = _get_engine()
        result, elapse = engine(tmp_path)
        if not result:
            return "", []

        logger.debug(
            "RapidOCR: %.2fs (detect=%.2f cls=%.2f rec=%.2f) %d regions",
            sum(elapse) if elapse else 0,
            elapse[0] if elapse else 0,
            elapse[1] if elapse else 0,
            elapse[2] if elapse else 0,
            len(result),
        )

        lines: list[str] = []
        boxes: list[tuple[int, int, str, float, list]] = []
        for box, text, conf in result:
            txt = text.strip()
            if not txt:
                continue
            # box = [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]
            y_coords = [p[1] for p in box]
            ymin, ymax = int(min(y_coords)), int(max(y_coords))
            lines.append(txt)
            conf_val = float(conf) if not isinstance(conf, (int, float)) else conf
            boxes.append((ymin, ymax, txt, conf_val, box))

        return "\n".join(lines), sorted(boxes, key=lambda b: b[0])
    finally:
        import os

        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def ocr_image_file(file_path: str) -> tuple[str, list]:
    """OCR an image file → text + boxes."""
    from pathlib import Path

    return ocr_image_bytes(Path(file_path).read_bytes())


# ── Formula detection ─────────────────────────────────────────────

# ── CJK detection (for formula merge logic) ──
_HAS_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# Patterns that suggest a text region contains math / chemistry formulas
_FORMULA_RE = re.compile(
    r"("
    r"[=＝→←⇌↑↓↔⇄⇆↗↘]"               # math / chem arrow & equals
    r"|" r"[₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎]"         # Unicode subscripts / operators (may be dropped)
    r"|" r"\b[A-Z][a-z]?\d{1,4}"       # element + count: H2, Na2, Fe3O4
    r"|" r"\d[A-Z][a-z]?\b"            # count + element: 2H, 3Fe
    r"|" r"[A-Z][a-z]?[A-Z0-9]"        # dropped-subscript chemistry: HCl→HC, NaOH→NaO
    r"|" r"[αβγδεζηθικλμνξπρστυφχψω]"  # Greek letters
    r"|" r"====|══"                     # chemical equation separators
    r")"
)

# Secondary check: formula line must also have == or + (avoid false positives
# on text pages that just mention element names)
_FORMULA_CONFIRM_RE = re.compile(r"[=＝+]")


def has_formula(text: str) -> bool:
    """Return True when *text* likely contains math / chemistry formulas.

    Requires BOTH a chemistry symbol pattern AND a formula operator (==, +)
    to avoid false positives on text pages that merely mention element names.
    """
    if not _FORMULA_RE.search(text):
        return False
    # Secondary: must have formula operators (==, +, or =)
    return bool(_FORMULA_CONFIRM_RE.search(text))


def get_formula_lines(
    boxes: list[tuple[int, int, str, float, list]],
) -> list[tuple[int, int, str, list]]:
    """Return only lines whose text matches formula patterns.

    Each item: (ymin, ymax, text, bbox_4pt)
    """
    return [
        (ymin, ymax, txt, bbox)
        for ymin, ymax, txt, conf, bbox in boxes
        if has_formula(txt)
    ]


def crop_formula_regions(
    high_res_image,  # numpy BGR array (200 DPI, before downscale)
    boxes: list[tuple[int, int, str, float, list]],
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> list[bytes]:
    """Crop formula regions from a high-resolution page image.

    Merges adjacent formula lines (gap < 2× line height), then crops each
    merged region from *high_res_image* at original resolution.

    Args:
        high_res_image: numpy BGR array at original DPI.
        boxes: OCR results from ``ocr_image_bytes()``, sorted by y.
        scale_x, scale_y: ratio from RapidOCR's 600px coords → high-res coords.

    Returns:
        List of PNG-encoded bytes, one per merged formula region.
    """
    import cv2, numpy as np

    formula_boxes = get_formula_lines(boxes)
    if not formula_boxes:
        return []

    # Merge adjacent formula lines (gap ≤ 2× avg line height)
    line_heights = [ymax - ymin for ymin, ymax, _, _ in formula_boxes]
    avg_h = sum(line_heights) / len(line_heights) if line_heights else 40
    gap_threshold = avg_h * 2

    merged: list[tuple[int, int]] = []
    cur_ymin = formula_boxes[0][0]
    cur_ymax = formula_boxes[0][1]

    for ymin, ymax, _, _ in formula_boxes[1:]:
        if ymin - cur_ymax <= gap_threshold and (ymax - ymin) > 0:
            cur_ymax = ymax
        else:
            merged.append((cur_ymin, cur_ymax))
            cur_ymin, cur_ymax = ymin, ymax
    merged.append((cur_ymin, cur_ymax))

    # Scale to high-res coordinates
    img_h, img_w = high_res_image.shape[:2]
    crops: list[bytes] = []
    pad = 4  # px padding

    for ymin, ymax in merged:
        x0 = 0
        x1 = img_w
        y0 = max(0, int(ymin * scale_y) - pad)
        y1 = min(img_h, int(ymax * scale_y) + pad)
        if y1 <= y0 or x1 <= x0:
            continue
        crop = high_res_image[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        _, buf = cv2.imencode(".png", crop, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        crops.append(buf.tobytes())

    return crops


# ── Combined pipeline ─────────────────────────────────────────────


def ocr_text_only(image_bytes: bytes) -> str:
    """Convenience: OCR → plain text (throw away box info)."""
    text, _ = ocr_image_bytes(image_bytes)
    return text


# ── Formula line merger ────────────────────────────────────────────


def merge_formula_lines(lines: list[str]) -> list[str]:
    """Merge consecutive formula-fragment lines into one.

    RapidOCR may split "Fe + CuSO₄ == FeSO₄ + Cu" across 3 lines:
    "Fe + CuSO", "= FeSO", "+ Cu".  This merges adjacent lines that
    contain element symbols but no CJK characters.
    """
    if not lines:
        return []

    merged: list[str] = []
    pending = ""
    for line in lines:
        _is_formula = has_formula(line)
        _has_cjk = bool(_HAS_CJK.search(line))
        if _is_formula and not _has_cjk and pending:
            pending += " " + line
            continue
        if pending:
            merged.append(pending)
        pending = line
    if pending:
        merged.append(pending)
    return merged
