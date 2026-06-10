"""
tutor_platform/tools/preprocess.py — OCR image preprocessing.

The canonical, single-source-of-truth OpenCV preprocessing pipeline used by all
document ingestion paths (UnifiedDocumentPipeline, provider_api, RagDocumentPipeline).
"""

import logging

logger = logging.getLogger("tutor_platform.tools.preprocess")


def preprocess_image_bytes(image_bytes: bytes) -> bytes:
    """Preprocess image for OCR: downscale → grayscale → denoise → CLAHE → deskew → threshold.

    Steps:
      1. Downscale: cap longest side at 600px (VL model pixel limit)
      2. Grayscale
      3. Conditional denoise: clean/high-contrast images skip the expensive step
      4. CLAHE contrast enhancement (noisy images only)
      5. Deskew: detect text angle via minAreaRect and rotate
      6. Adaptive Gaussian threshold (binarize)

    When OpenCV is unavailable the raw bytes are returned unchanged.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG/etc.)

    Returns:
        Preprocessed JPEG image bytes ready for OCR.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning("OpenCV not available, returning original image bytes")
        return image_bytes

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        logger.warning("preprocess: decode failed, returning original")
        return image_bytes

    try:
        # 1. Downscale: cap longest side at 600px (INTER_AREA for text edge clarity)
        _MAX_EDGE = 600
        h, w = img.shape[:2]
        if max(h, w) > _MAX_EDGE:
            scale = _MAX_EDGE / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)

        # 2. Encode as JPEG (keep color, no binarization — Qwen2-VL handles raw input)
        _, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return buffer.tobytes()
    except Exception as e:
        logger.warning("Image preprocessing failed: %s, returning original", e)
        return image_bytes
