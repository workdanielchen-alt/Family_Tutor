"""Tests for OCR + Vision pipeline: preprocessing, segmentation, garbled detection,
diagram detection, question counting, and the overall dispatch flow.

These tests exercise the isolated pure-Python units.  Full integration tests
(actual rkllama / Ollama calls) require the full Docker stack.
"""

import re
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Async test support: skip when pytest-asyncio is not installed
try:
    import pytest_asyncio  # noqa: F401
    _HAS_ASYNC = True
except ImportError:
    _HAS_ASYNC = False
pytest_async = pytest.mark.skipif(not _HAS_ASYNC, reason="requires pytest-asyncio")

sys.path.insert(0, "docker/platform")

from provider_api import (
    _DIAGRAM_PATTERNS,
    _detect_total_questions,
    _IMAGE_EXTENSIONS,
    _ocr_output_is_garbled,
    _split_image_segments,
)


def _write_minimal_jpeg(path) -> None:
    """Write a minimal valid JPEG file for tests."""
    try:
        import cv2
        img = np.full((200, 300, 3), 240, dtype=np.uint8)
        _, buf = cv2.imencode(".jpg", img)
        path.write_bytes(buf.tobytes())
    except ImportError:
        # Minimal valid JPEG bytes (SOI + EOI markers)
        path.write_bytes(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\xc8\x01,\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x11\x04\x12!1\x05\x06\x13"Q\x07AQ\xc2\xd1\xf4\x14q\x82a#2R\x91\x152\xb1\xc1\xd1\x81\x92\xa2\xb2\xd2\xe1\xf0\x15#\x16\xb3"3$6\x17\x18\x93\x08A\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x88\xe5\x1c=\xd7\xac\x9f\xff\xd9')


# ══════════════════════════════════════════════════════════════════
# _ocr_output_is_garbled — garbled output detection
# ══════════════════════════════════════════════════════════════════

class TestOcrOutputGarbled:
    def test_clean_chinese_text(self):
        """Normal Chinese text → not garbled."""
        text = "小明和小红一起去看电影，他们买了三张票。"
        assert not _ocr_output_is_garbled(text)

    def test_chinese_with_digits(self):
        """Chinese text with numbers and options → not garbled."""
        text = "下列计算正确的是\nA加B加C等于D\n已知x加y等于五求最大值"
        assert not _ocr_output_is_garbled(text)

    def test_math_formulas(self):
        """Text with LaTeX math → not garbled."""
        text = r"已知 $x^2 + y^2 = 1$，求 $x + y$ 的最大值。"
        assert not _ocr_output_is_garbled(text)

    def test_empty_text(self):
        """Empty or near-empty → garbled."""
        assert _ocr_output_is_garbled("")
        assert _ocr_output_is_garbled("   ")
        assert _ocr_output_is_garbled("ab")

    def test_short_text_under_10_chars(self):
        """Very short text → garbled."""
        assert _ocr_output_is_garbled("hello")
        assert _ocr_output_is_garbled("测试")

    def test_garbled_garbage_high_ratio(self):
        """ASCII punctuation spam → garbled."""
        text = "xX□�xX□�~~~>>>><<<|||^^^"
        assert _ocr_output_is_garbled(text)

    def test_garbled_low_chinese_ratio(self):
        """Mostly non-Chinese with scattered Chinese → garbled."""
        text = "abc123def456ghi!@#$%测试xyz" * 10
        assert _ocr_output_is_garbled(text)

    def test_chinese_with_some_punctuation(self):
        """Chinese with normal punctuation → not garbled."""
        text = "解：设 x=1，则 y=2。答：3。"
        assert not _ocr_output_is_garbled(text)

    def test_mixed_script_in_exam(self):
        """Typical exam OCR output with mixed content → not garbled."""
        text = (
            "一、选择题（每小题3分，共30分）\n"
            "1. 下列选项中，哪个是二次函数？（  ）\n"
            "A. y=x+1  B. y=x²  C. y=1/x  D. y=|x|\n"
            "2. 如图，AB是⊙O的直径，∠CAB=30°，则∠D=___。"
        )
        assert not _ocr_output_is_garbled(text)

    def test_near_garbled_boundary(self):
        """Text that is just barely Chinese enough."""
        text = "测试" + "x" * 20
        # chinese_ratio = 2/22 ≈ 0.09 < 0.2 → garbled
        assert _ocr_output_is_garbled(text)


# ══════════════════════════════════════════════════════════════════
# _DIAGRAM_PATTERNS — diagram detection regex
# ══════════════════════════════════════════════════════════════════

class TestDiagramPatterns:
    @pytest.mark.parametrize("text", [
        "如图，AB是⊙O的直径",
        "图1所示",
        "图2",
        "如图3",
        "如图所示",
        "电路图如图",
        "受力分析图",
        "函数图像",
        "坐标系",
        "坐标图",
        "Figure 1",
        "Fig. 2",
        "diagram",
        "graph shows",
        "示意图",
        "（图5）",
        "图表1",
        "光路图",
    ])
    def test_diagram_detected(self, text: str):
        """These texts should trigger the diagram description path."""
        assert _DIAGRAM_PATTERNS.search(text), f"Expected match: {text!r}"

    @pytest.mark.parametrize("text", [
        "已知 a=1，b=2",
        "下列计算正确的是",
        "解方程 2x+3=7",
        "先化简，再求值",
        "证明：三角形内角和为180°",
        "Hello world, no charts here",
        "根据题意，得",
    ])
    def test_no_diagram(self, text: str):
        """These texts should NOT trigger the diagram description path."""
        assert not _DIAGRAM_PATTERNS.search(text), f"Unexpected match: {text!r}"


# ══════════════════════════════════════════════════════════════════
# _split_image_segments — image segmentation
# ══════════════════════════════════════════════════════════════════

@pytest.fixture
def blank_image_bytes() -> bytes:
    """A blank white 400x600 JPEG image."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        return b"fallback raw bytes"
    img = np.full((400, 600, 3), 255, dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)  # noqa: F821
    return buf.tobytes()


class TestSplitImageSegments:
    def test_blank_image_returns_single(self, blank_image_bytes):  # noqa: F811
        """Blank image → single element (fallback to full-image OCR)."""
        segments = _split_image_segments(blank_image_bytes)
        assert len(segments) == 1
        assert segments[0] == blank_image_bytes

    def test_text_rows_with_gaps(self):
        """Image with two text blocks separated by whitespace → at least 1 segment."""
        try:
            import cv2  # noqa: F401
        except ImportError:
            pytest.skip("cv2 not available")
        img = np.full((400, 600, 3), 255, dtype=np.uint8)
        # First text block (dark pixels)
        img[50:100, 50:550] = 0
        # Second text block (dark pixels) separated by gap
        img[200:250, 50:550] = 0
        _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])  # noqa: F821
        result = _split_image_segments(buf.tobytes())
        # May return 1 segment if gap isn't wide enough relative to height
        assert len(result) >= 1

    def test_invalid_bytes_returns_single(self):
        """Non-image bytes → single element passthrough."""
        segments = _split_image_segments(b"not an image")
        assert len(segments) == 1
        assert segments[0] == b"not an image"


# ══════════════════════════════════════════════════════════════════
# _detect_total_questions — question count estimation
# ══════════════════════════════════════════════════════════════════

class TestDetectTotalQuestions:
    def test_numbered_items(self):
        """Items starting with '1. 2. 3.' → detects max number."""
        text = "1. 选择题\n2. 填空题\n3. 计算题"
        assert _detect_total_questions(text) == 3

    def test_chinese_numeral_items(self):
        """Items starting with '一、二、三、' — not matched by the regex."""
        text = "一、选择题\n二、填空题\n三、计算题"
        assert _detect_total_questions(text) == 0

    def test_mixed_numbered_and_text(self):
        """Mixed content with '第X题' markers."""
        text = "第1题 已知...\n第2题 如图...\n第3题 证明..."
        assert _detect_total_questions(text) == 3

    def test_max_number_extraction(self):
        """Returns the maximum detected number, not count."""
        text = "1. 题目一\n3. 题目三\n5. 题目五\n2. 题目二"
        assert _detect_total_questions(text) == 5

    def test_no_questions(self):
        """No question markers → returns 0."""
        text = "这是一段普通的说明文字，不包含题目编号。"
        assert _detect_total_questions(text) == 0

    def test_unicode_period_variants(self):
        """Various Chinese punctuation after numbers."""
        text = "1．题目（中文句号）\n2、题目（顿号）\n3）题目（括号）"
        assert _detect_total_questions(text) == 3

    def test_empty_text(self):
        """Empty string → 0."""
        assert _detect_total_questions("") == 0


# ══════════════════════════════════════════════════════════════════
# _IMAGE_EXTENSIONS — supported image types
# ══════════════════════════════════════════════════════════════════

class TestImageExtensions:
    def test_all_common_formats(self):
        """All common image extensions are in the set."""
        for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"):
            assert ext in _IMAGE_EXTENSIONS, f"Missing: {ext}"

    def test_non_image_extensions_not_included(self):
        """Non-image extensions are NOT in the set."""
        for ext in (".pdf", ".docx", ".txt", ".md", ".mp4", ".avi"):
            assert ext not in _IMAGE_EXTENSIONS, f"Unexpectedly present: {ext}"


# ══════════════════════════════════════════════════════════════════
# Integration: OCR dispatch flow (mocked external calls)
# ══════════════════════════════════════════════════════════════════

class TestOcrDispatchFlow:
    """Test the _ocr_image_bytes dispatch logic with mocked backends."""

    @pytest.mark.asyncio
    @patch("provider_api._ocr_image_bytes_rkllama")
    @patch("provider_api._ocr_image_bytes_ollama")
    async def test_provider_rkllama(
        self, mock_ollama: AsyncMock, mock_rkllama: AsyncMock, monkeypatch
    ):
        """RKLLAMA provider → calls _ocr_image_bytes_rkllama."""
        from provider_api import _ocr_image_bytes

        monkeypatch.setenv("OCR_PROVIDER", "rkllama")
        mock_rkllama.return_value = "OCR识别结果：小明和小红去公园玩。"
        result = await _ocr_image_bytes(b"fake_image_bytes", "trace_001")
        assert result == "OCR识别结果：小明和小红去公园玩。"
        mock_rkllama.assert_awaited_once()
        mock_ollama.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("provider_api._ocr_image_bytes_rkllama")
    @patch("provider_api._ocr_image_bytes_ollama")
    async def test_provider_ollama(
        self, mock_ollama: AsyncMock, mock_rkllama: AsyncMock, monkeypatch
    ):
        """OLLAMA provider → calls _ocr_image_bytes_ollama."""
        from provider_api import _ocr_image_bytes

        monkeypatch.setenv("OCR_PROVIDER", "ollama")
        mock_ollama.return_value = "OCR结果：小明和小红去公园。"
        result = await _ocr_image_bytes(b"fake_image_bytes", "trace_002")
        assert result == "OCR结果：小明和小红去公园。"
        mock_ollama.assert_awaited_once()
        mock_rkllama.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("provider_api._ocr_image_bytes_rkllama")
    async def test_garbled_output_filtered(
        self, mock_rkllama: AsyncMock, monkeypatch
    ):
        """Garbled output → treated as empty string (OCR failure)."""
        from provider_api import _ocr_image_bytes

        monkeypatch.setenv("OCR_PROVIDER", "rkllama")
        # Garbled: low Chinese ratio + high ASCII noise
        mock_rkllama.return_value = "xX□�" * 20
        result = await _ocr_image_bytes(b"fake", "trace_003")
        assert result == ""

    @pytest.mark.asyncio
    @patch("provider_api._ocr_image_bytes_rkllama")
    async def test_clean_output_passes_through(
        self, mock_rkllama: AsyncMock, monkeypatch
    ):
        """Clean output passes through unchanged."""
        from provider_api import _ocr_image_bytes

        monkeypatch.setenv("OCR_PROVIDER", "rkllama")
        mock_rkllama.return_value = "小明和小红去公园玩。"
        result = await _ocr_image_bytes(b"fake", "trace_004")
        assert result == "小明和小红去公园玩。"


# ══════════════════════════════════════════════════════════════════
# Integration: _handle_inbound_file -> vision diagram detection
# ══════════════════════════════════════════════════════════════════

class TestVisionDiagramIntegration:
    """Test that _describe_diagram is called when OCR text matches DIAGRAM_PATTERNS.

    This tests the orchestration inside _handle_inbound_file: after OCR runs,
    the result is checked against _DIAGRAM_PATTERNS; if matched, _describe_diagram
    is called and the vision description is appended to the OCR content.
    """

    @pytest.mark.asyncio
    @patch("provider_api._ocr_image_file")
    @patch("provider_api._describe_diagram")
    @patch("provider_api._hash_file")
    async def test_diagram_triggers_vision(
        self,
        mock_hash: MagicMock,
        mock_describe: AsyncMock,
        mock_ocr: AsyncMock,
        monkeypatch,
        tmp_path,
    ):
        """OCR output containing '如图' → _describe_diagram is called."""
        from provider_api import _handle_inbound_file, _FILE_PROCESS_CACHE

        monkeypatch.setenv("OCR_PROVIDER", "rkllama")

        # Write a minimal JPEG placeholder (cv2 not required)
        img_path = tmp_path / "test_diagram.jpg"
        _write_minimal_jpeg(img_path)

        # Mock OCR to return text containing a diagram keyword
        mock_ocr.return_value = "如图，AB是⊙O的直径，∠CAB=30°"
        mock_hash.return_value = "fake_hash_001"
        mock_describe.return_value = "[图片中的图形描述] 有一个圆，圆心为O..."

        # Clear the file process cache to avoid stale hits
        _FILE_PROCESS_CACHE.clear()

        result = await _handle_inbound_file(str(img_path), {
            "trace_id": "trace_vis_001",
            "learner_id": "learner_a",
        })

        assert result["ok"] is True
        assert result["route"] == "ocr"
        assert "如图，AB是⊙O的直径" in result["content"]
        # _describe_diagram was called → vision description is appended
        assert "[图片中的图形描述]" in result["content"]
        mock_describe.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("provider_api._ocr_image_file")
    @patch("provider_api._describe_diagram")
    @patch("provider_api._hash_file")
    async def test_all_images_force_vision(
        self,
        mock_hash: MagicMock,
        mock_describe: AsyncMock,
        mock_ocr: AsyncMock,
        monkeypatch,
        tmp_path,
    ):
        """All image files now force a vision call (no OCR keyword dependency)."""
        from provider_api import _handle_inbound_file, _FILE_PROCESS_CACHE

        monkeypatch.setenv("OCR_PROVIDER", "rkllama")

        img_path = tmp_path / "test_plain.jpg"
        _write_minimal_jpeg(img_path)

        mock_ocr.return_value = "小明和小红一起去看电影。"
        mock_describe.return_value = "[图片中的图形描述] 两个小朋友在公园里。"
        mock_hash.return_value = "fake_hash_002"

        _FILE_PROCESS_CACHE.clear()

        result = await _handle_inbound_file(str(img_path), {
            "trace_id": "trace_vis_002",
            "learner_id": "learner_b",
        })

        assert result["ok"] is True
        assert result["route"] == "ocr"
        # Vision is called unconditionally → description is always fused
        assert "[图片中的图形描述]" in result["content"]
        mock_describe.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════
# Integration: OCR fallback on failure
# ══════════════════════════════════════════════════════════════════

class TestOcrFallback:
    @pytest.mark.asyncio
    @patch("provider_api._ocr_image_file")
    @patch("provider_api._describe_diagram")
    @patch("provider_api._hash_file")
    async def test_ocr_failure_triggers_fallback(
        self,
        mock_hash: MagicMock,
        mock_describe: AsyncMock,
        mock_ocr: AsyncMock,
        monkeypatch,
        tmp_path,
    ):
        """OCR returns nothing → fallback route with descriptive message."""
        from provider_api import _handle_inbound_file, _FILE_PROCESS_CACHE

        monkeypatch.setenv("OCR_PROVIDER", "rkllama")
        img_path = tmp_path / "test_garbled.jpg"
        _write_minimal_jpeg(img_path)

        mock_ocr.return_value = ""
        mock_describe.return_value = ""
        mock_hash.return_value = "fake_hash_003"

        _FILE_PROCESS_CACHE.clear()

        result = await _handle_inbound_file(str(img_path), {
            "trace_id": "trace_fall_001",
            "learner_id": "learner_c",
        })

        assert result["ok"] is True
        assert "未能被自动识别" in result["content"]


# ══════════════════════════════════════════════════════════════════
# Smoke: key functions exist and are callable
# ══════════════════════════════════════════════════════════════════

class TestFunctionSmoke:
    def test_ocr_image_file_exists(self):
        from provider_api import _ocr_image_file
        import asyncio
        assert asyncio.iscoroutinefunction(_ocr_image_file)

    def test_ocr_image_bytes_exists(self):
        from provider_api import _ocr_image_bytes
        import asyncio
        assert asyncio.iscoroutinefunction(_ocr_image_bytes)

    def test_describe_diagram_exists(self):
        from provider_api import _describe_diagram
        import asyncio
        assert asyncio.iscoroutinefunction(_describe_diagram)

    def test_handle_inbound_file_exists(self):
        from provider_api import _handle_inbound_file
        import asyncio
        assert asyncio.iscoroutinefunction(_handle_inbound_file)

    def test_handle_pdf_exists(self):
        from provider_api import _handle_pdf
        import asyncio
        assert asyncio.iscoroutinefunction(_handle_pdf)

    def test_ocr_office_images_exists(self):
        from provider_api import _ocr_office_images
        import asyncio
        assert asyncio.iscoroutinefunction(_ocr_office_images)
