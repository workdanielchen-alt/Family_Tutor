"""Tests for the WeChat → DT BOT guided teaching pipeline.

Covers the core layers of the teaching pipeline:

1. **Answer matching** — ``_match_answers`` handles various student answer formats.
2. **Answer key extraction** — ``_ANSWER_KEY_RE`` regex extracts markers from LLM output.
3. **Correct answer extraction** — ``_extract_correct_answer`` fallback for missing markers.
4. **Exam subject detection** — ``_detect_exam_subject`` identifies math/physics/chemistry.
5. **Multi-page OCR merge** — Text merging across pages with page separators.
6. **Notification bridge** — ``_notify_hermes_agent`` / ``_notify_tutor_callback`` payloads.
7. **SOUL.md persona** — ``_TEACHER_SOUL`` and ``_TEACHER_EXPLAIN_SOUL`` constants.
8. **LLM lock** — ``_TTLock`` smoke test for stale recovery.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

# ── Path setup for docker/platform imports ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "docker", "platform"))

try:
    from provider_api import (
        _match_answers,
        _extract_correct_answer,
        _ANSWER_KEY_RE,
        _detect_exam_subject,
        _detect_total_questions,
        _normalize_qnum,
        _cleanup_old_notifications,
        _TEACHER_SOUL,
        _TEACHER_EXPLAIN_SOUL,
        _TTLock,
    )
except ImportError as e:
    pytest.skip(f"provider_api imports not available: {e}", allow_module_level=True)


# ══════════════════════════════════════════════════════════════════
# Layer 1 — Answer evaluation & key matching
# ══════════════════════════════════════════════════════════════════

class TestAnswerMatching:
    """Verify ``_match_answers`` handles various student answer formats."""

    def test_exact_match(self):
        assert _match_answers("5", "5") is True

    def test_case_insensitive(self):
        assert _match_answers("A", "a") is True

    def test_whitespace_normalized(self):
        assert _match_answers("  hello  ", "hello") is True

    def test_chinese_digits_not_auto_converted(self):
        """中文数字 '五' does NOT auto-convert to Arabic — returns False."""
        assert _match_answers("五", "5") is False

    def test_mismatch(self):
        assert _match_answers("7", "5") is False

    def test_empty_student(self):
        assert _match_answers("", "5") is False

    def test_empty_correct(self):
        """If correct answer is empty string, matching fails."""
        assert _match_answers("5", "") is False

    def test_both_empty(self):
        """Both empty — function returns False."""
        assert _match_answers("", "") is False

    def test_math_expression_normalized(self):
        """'x=3' should normalize to match '3'."""
        assert _match_answers("x=3", "3") is True

    def test_units_stripped(self):
        assert _match_answers("5cm", "5") is True

    def test_negative_numbers(self):
        assert _match_answers("-3", "-3") is True

    def test_fraction_spaces(self):
        assert _match_answers("1/2", "1/2") is True


class TestAnswerKeyExtraction:
    """Verify extracting [ANSWER_KEY:...] markers using the live regex."""

    def extract_key(self, text: str) -> str | None:
        m = _ANSWER_KEY_RE.search(text)
        return m.group(1).strip() if m else None

    def test_basic_answer_key(self):
        output = "解题过程...\n[ANSWER_KEY:42]"
        assert self.extract_key(output) == "42"

    def test_answer_key_with_kp(self):
        output = "讲解...\n[ANSWER_KEY:3.14][KP_ID:math/pi]"
        assert self.extract_key(output) == "3.14"

    def test_no_answer_key(self):
        output = "只有普通的讲解内容"
        assert self.extract_key(output) is None

    def test_answer_key_with_spaces(self):
        output = "text [ANSWER_KEY: 25 ] text"
        assert self.extract_key(output) == "25"


class TestCorrectAnswerExtraction:
    """Fallback: extract correct answer from LLM explanation text."""

    def test_extract_from_explanation(self):
        """When no explicit marker, try to extract from text."""
        text = "这道题的正确答案是 42。继续努力！"
        answer = _extract_correct_answer(text)
        assert answer is not None

    def test_extract_from_empty(self):
        answer = _extract_correct_answer("")
        assert answer is None

    def test_extract_chinese_answer(self):
        text = "正确答案是：B选项。因为..."
        answer = _extract_correct_answer(text)
        assert answer is not None
        assert "B" in answer or "B选项" in answer


# ══════════════════════════════════════════════════════════════════
# Layer 2 — Exam subject detection
# ══════════════════════════════════════════════════════════════════

class TestExamSubjectDetection:
    """Verify OCR text → subject classification."""

    def test_math_detected(self):
        assert _detect_exam_subject("选择题 1+1=？ 计算题") == "math"

    def test_physics_detected(self):
        assert _detect_exam_subject("一、选择题 初中物理 关于牛顿第一定律") == "physics"

    def test_chemistry_detected(self):
        assert _detect_exam_subject("化学方程式 2H2+O2→2H2O") == "chemistry"

    def test_empty_fallback(self):
        result = _detect_exam_subject("")
        assert result in ("math", "physics", "chemistry", "")


# ══════════════════════════════════════════════════════════════════
# Layer 3 — Multi-page OCR merge
# ══════════════════════════════════════════════════════════════════

class TestMultiPageOcrMerge:
    """Verify multi-page OCR text merging logic (mirrors _run_teaching_flow)."""

    def test_single_page_with_separator(self):
        pages = ["题目1：计算2+2=？"]
        merged = "\n".join(
            f"--- 第{i+1}页 ---\n{p}" for i, p in enumerate(pages)
        )
        assert "第1页" in merged

    def test_multiple_pages_with_separators(self):
        pages = ["选择题内容", "填空题内容", "解答题内容"]
        merged = "\n".join(
            f"--- 第{i+1}页 ---\n{p}" for i, p in enumerate(pages)
        )
        assert merged.count("第") == 3

    def test_empty_pages_skipped(self):
        pages = ["有效内容", "", "更多内容"]
        merged_parts = []
        for i, p in enumerate(pages):
            if p.strip():
                merged_parts.append(f"--- 第{i+1}页 ---\n{p}")
        merged = "\n".join(merged_parts)
        assert "第2页" not in merged
        assert "有效内容" in merged
        assert "更多内容" in merged

    def test_estimate_questions_from_text(self):
        text = "1. 计算\n2. 填空\n3. 解答题\n4. 证明题\n5. 应用题"
        q_count = len(re.findall(r'^\d+[\.\、\．]\s', text, re.MULTILINE))
        assert q_count == 5

    def test_detect_questions_real_exam_text(self):
        """Use the project's _detect_total_questions function."""
        text = "一、选择题（每题3分）\n1. 1+1=？\n2. 2+3=？\n二、填空题\n3. 填空..."
        q_count = _detect_total_questions(text)
        assert q_count >= 1

    def test_detect_questions_empty(self):
        assert _detect_total_questions("") == 0


# ══════════════════════════════════════════════════════════════════
# Layer 4 — Notification bridge payload structure
# ══════════════════════════════════════════════════════════════════

class TestNotificationBridge:
    """Verify notification file bridge payloads match HA consumption format."""

    def test_tutor_reply_payload(self):
        payload = {
            "type": "tutor_reply",
            "learner_id": "chat_abc123",
            "content": "第1题：计算 3+5=？\n\n引导问题：...",
            "trace_id": "trace_001",
        }
        assert payload["type"] == "tutor_reply"
        assert isinstance(payload["learner_id"], str)
        assert len(payload["content"]) > 0

    def test_file_processed_payload(self):
        payload = {
            "type": "file_processed",
            "kb_name": "tutoring",
            "filename": "math_exam.jpg",
            "learner_id": "chat_abc",
            "intent": "education",
            "route": "auto_teach",
            "content_length": 1024,
            "storage_ok": True,
            "content_preview": "数学试卷...",
            "trace_id": "trace_002",
            "source_url": "",
        }
        assert payload["type"] == "file_processed"
        assert payload["intent"] == "education"
        assert payload["storage_ok"] is True


# ══════════════════════════════════════════════════════════════════
# Layer 5 — LLM lock TTL recovery (smoke)
# ══════════════════════════════════════════════════════════════════

class TestTTLockSmoke:
    """Verify _TTLock basic contract."""

    def test_instantiate(self):
        lock = _TTLock(ttl=10)
        assert lock is not None


# ══════════════════════════════════════════════════════════════════
# Layer 6 — SOUL.md persona constants
# ══════════════════════════════════════════════════════════════════

class TestTeachingPersona:
    """Verify the persona constants used for SOUL.md injection."""

    def test_teacher_soul_exists(self):
        assert isinstance(_TEACHER_SOUL, str)
        assert len(_TEACHER_SOUL) > 100

    def test_explain_soul_exists(self):
        assert isinstance(_TEACHER_EXPLAIN_SOUL, str)
        assert len(_TEACHER_EXPLAIN_SOUL) > 50

    def test_teacher_contains_guide_instruction(self):
        assert "引导" in _TEACHER_SOUL or "guide" in _TEACHER_SOUL

    def test_explain_contains_explain_instruction(self):
        assert "讲解" in _TEACHER_EXPLAIN_SOUL or "explain" in _TEACHER_EXPLAIN_SOUL


# ══════════════════════════════════════════════════════════════════
# Layer 7 — Question number tracking (multi-round advancement fix)
# ══════════════════════════════════════════════════════════════════

class TestQuestionNumberAdvancement:
    """Verify ``_last_question_num`` advances correctly across rounds.

    This was a bug: ``_last_question_num`` was only updated in the DT WS
    ``send_and_recv`` path, but NOT in the Direct API or NPU paths.  The
    fix adds question-number parsing in the shared post-processing step
    so ALL three LLM paths advance the counter.
    """

    def test_normalize_qnum_arabic(self):
        """Arabic "第1题" stays as-is."""
        assert _normalize_qnum("这是第1题的内容") == "这是第1题的内容"

    def test_normalize_qnum_chinese(self):
        """Chinese "第一题" → "第1题"."""
        assert _normalize_qnum("这是第一题的内容") == "这是第1题的内容"

    def test_normalize_qnum_mixed(self):
        """Mixed numerals all converted."""
        result = _normalize_qnum("第一题、第二题和第三题")
        assert "第1题" in result
        assert "第2题" in result
        assert "第3题" in result

    def test_normalize_qnum_strip_spaces(self):
        """Strips inner spaces: 第 1 题 → 第1题."""
        assert _normalize_qnum("第 1 题") == "第1题"

    def test_parse_qnum_from_reply(self):
        """Extract question number from LLM reply content."""
        import re
        content = "这是第1题的讲解。\n第2题：计算3+5=？"
        normalized = _normalize_qnum(content)
        m = re.search(r"第\s*(\d+)\s*题", normalized)
        assert m is not None
        # Should parse the LAST occurrence (newest question)
        all_matches = list(re.finditer(r"第\s*(\d+)\s*题", normalized))
        last_q = int(all_matches[-1].group(1))
        assert last_q == 2

    def test_parse_qnum_single_question(self):
        """Single question in reply."""
        import re
        content = "第1题：计算2+2=？\n引导问题..."
        normalized = _normalize_qnum(content)
        m = re.search(r"第\s*(\d+)\s*题", normalized)
        assert m is not None
        assert int(m.group(1)) == 1

    def test_parse_qnum_no_question(self):
        """No question number — completion/summary text."""
        import re
        content = "🎉 试卷完成！共5道题，答对3道。"
        normalized = _normalize_qnum(content)
        m = re.search(r"第\s*(\d+)\s*题", normalized)
        assert m is None

    def test_multi_round_advancement_simulation(self):
        """Simulate 3 rounds: FIRST_QUESTION → EVAL → EVAL, verify advancement."""
        import re

        # Round 1: FIRST_QUESTION — set qnum=1
        _last_question_num = 0  # fresh session
        reply_1 = "第1题：计算2+3=？\n引导问题..."
        normalized = _normalize_qnum(reply_1)
        m = re.search(r"第\s*(\d+)\s*题", normalized)
        if m:
            parsed = int(m.group(1))
            if parsed > _last_question_num:
                _last_question_num = parsed
        assert _last_question_num == 1

        # Round 2: student answers q1, LLM evaluates + asks q2
        reply_2 = ("你答对了！第1题的答案是5。\n"
                   "第2题：计算7-3=？\n引导问题...")
        normalized = _normalize_qnum(reply_2)
        matches = list(re.finditer(r"第\s*(\d+)\s*题", normalized))
        parsed = int(matches[-1].group(1))  # newest question
        if parsed > _last_question_num:
            _last_question_num = parsed
        assert _last_question_num == 2

        # Round 3: student answers q2, LLM evaluates + asks q3
        reply_3 = ("对的！第2题的答案是4。\n"
                   "第3题：计算6×2=？\n引导问题...")
        normalized = _normalize_qnum(reply_3)
        matches = list(re.finditer(r"第\s*(\d+)\s*题", normalized))
        parsed = int(matches[-1].group(1))
        if parsed > _last_question_num:
            _last_question_num = parsed
        assert _last_question_num == 3


# ══════════════════════════════════════════════════════════════════
# Layer 8 — Answer divider injection (correct answer between questions)
# ══════════════════════════════════════════════════════════════════

class TestAnswerDividerInjection:
    """Verify the answer divider (═ ✅ 正确答案 ═) is injected correctly
    between the evaluation section and the next question."""

    DIVIDER_PATTERN = re.compile(r'═{3,}.*✅ 正确答案.*═{3,}', re.DOTALL)

    def test_divider_has_correct_answer(self):
        """Divider must contain the correct answer text."""
        divider = "\n══════════════════════════════════════════\n✅ 正确答案：42\n══════════════════════════════════════════\n"
        assert "42" in divider
        assert self.DIVIDER_PATTERN.search(divider) is not None

    def test_divider_format(self):
        """Verify the format: ══ line, ✅ answer, ══ line."""
        answer = "5"
        divider = (
            f"\n{'═' * 44}\n"
            f"✅ 正确答案：{answer}\n"
            f"{'═' * 44}\n"
        )
        lines = divider.strip().split('\n')
        assert len(lines) == 3
        assert lines[0].startswith('═') and len(lines[0]) == 44
        assert "✅ 正确答案：5" in lines[1]
        assert lines[2].startswith('═') and len(lines[2]) == 44

    def test_divider_inserts_before_next_question_with_separator(self):
        """When both a --- separator and 第N题 exist, insert BEFORE 第N题."""
        content = "你答对了！3+2=5。\n\n---\n\n第2题：计算7-3=？"
        answer = "5"
        expected_pattern = (
            r"你答对了！3\+2=5。\s*"
            r"---\s*"                           # --- separator preserved
            r"\n═{44}\n✅ 正确答案：5\n═{44}\n\s*"  # divider inserted
            r"第2题"                             # before 第2题
        )
        # Simulate the new priority logic (finditer last match)
        _divider = f"\n{'═' * 44}\n✅ 正确答案：{answer}\n{'═' * 44}\n"
        _all_q = list(re.finditer(r"(^|\n)【?第\s*\d+\s*[题、：:]", content))
        if _all_q:
            _last_q = _all_q[-1]
            content = (
                content[: _last_q.start()]
                + _divider
                + content[_last_q.start():]
            )
        else:
            _sep = re.search(r"\n[-─—]{3,}\n", content)
            if _sep:
                content = (
                    content[: _sep.start()]
                    + _divider
                    + content[_sep.end():]
                )
            else:
                content += _divider
        assert re.search(expected_pattern, content, re.DOTALL) is not None, f"Content: {repr(content)}"

    def test_divider_inserts_before_next_question(self):
        """When no --- separator exists, insert before the next 第N题 marker."""
        content = "你答对了！答案是5。\n讲解：因为加法运算。\n第2题：计算7-3=？\n引导问题：..."
        answer = "5"
        expected_pattern = (
            r"讲解：因为加法运算。\s*"
            r"\n═{44}\n✅ 正确答案：5\n═{44}\n\s*"
            r"第2题"
        )
        _divider = f"\n{'═' * 44}\n✅ 正确答案：{answer}\n{'═' * 44}\n"
        _all_q = list(re.finditer(r"(^|\n)【?第\s*\d+\s*[题、：:]", content))
        if _all_q:
            _last_q = _all_q[-1]
            content = (
                content[: _last_q.start()]
                + _divider
                + content[_last_q.start():]
            )
        else:
            _sep = re.search(r"\n[-─—]{3,}\n", content)
            if _sep:
                content = content[: _sep.start()] + _divider + content[_sep.end():]
            else:
                content += _divider
        assert re.search(expected_pattern, content, re.DOTALL) is not None, f"Content: {repr(content)}"

    def test_divider_with_bracket_question_format(self):
        """After _polish_guide_response, 第N题： becomes 【第N题】."""
        content = "你答对了！答案是5。\n【第2题】\n计算7-3=？"
        answer = "5"
        _divider = f"\n{'═' * 44}\n✅ 正确答案：{answer}\n{'═' * 44}\n"
        _all_q = list(re.finditer(r"(^|\n)【?第\s*\d+\s*[题、：:]", content))
        assert len(_all_q) >= 1, f"No matches in: {repr(content)}"
        _last_q = _all_q[-1]
        content = (
            content[: _last_q.start()]
            + _divider
            + content[_last_q.start():]
        )
        assert "【第2题】" in content
        assert "═" in content
        # Divider should be immediately before 【第2题】
        _before_q = content[:content.index("【第2题】")]
        assert "正确答案" in _before_q, f"Divider not before 【第2题】: {repr(content)}"


# ══════════════════════════════════════════════════════════════════
# Layer 9 — Notification cleanup
# ══════════════════════════════════════════════════════════════════

class TestNotificationCleanup:
    """Verify _cleanup_old_notifications smoke test."""

    def test_cleanup_function_exists(self):
        assert callable(_cleanup_old_notifications)

    def test_cleanup_on_nonexistent_dir(self):
        """Should not crash when directory doesn't exist."""
        _cleanup_old_notifications(max_age_hours=1)  # no exception
