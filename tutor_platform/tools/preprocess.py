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
      1. Downscale: cap longest side at 1800px (MiniCPM-V pixel limit)
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
        # 1. Downscale: cap longest side at 1800px (MiniCPM-V 1.8M pixel limit)
        _MAX_DIM = 1800
        h, w = img.shape[:2]
        if max(h, w) > _MAX_DIM:
            scale = _MAX_DIM / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_AREA)

        # 2. Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 3. Denoise only noisy images (clean screenshots skip the expensive step)
        _is_clean = gray.std() > 40
        if _is_clean:
            enhanced = gray
        else:
            denoised = cv2.fastNlMeansDenoising(gray)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(denoised)

        # 4. Deskew: detect text angle and rotate
        coords = np.column_stack(np.where(enhanced < 128))
        if len(coords) > 10:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = 90 + angle
            if abs(angle) > 0.3:
                h, w = enhanced.shape
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                enhanced = cv2.warpAffine(
                    enhanced, M, (w, h),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )

        # 5. Adaptive threshold (binarize)
        binary = cv2.adaptiveThreshold(
            enhanced, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2,
        )

        _, buffer = cv2.imencode(".jpg", binary, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return buffer.tobytes()
    except Exception as e:
        logger.warning("Image preprocessing failed: %s, returning original", e)
        return image_bytes
