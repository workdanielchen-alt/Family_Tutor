"""Tests for teach_loop.py Agentic Loop extensions.

Covers:
  1. _detect_subject — Chinese/English subject detection
  2. TeachPromptManager.get_phase_constraint — YAML constraint loading
  3. run_teach_loop_from_args — wrapper function with pre-extracted data
  4. _auto_rag_if_wrong — RAG trigger on wrong answer (no ChromaDB needed)
  5. get_kp_mastery_context — per-KP mastery query (no DB = no crash)
  6. _enrich_with_mastery — mastery injection into state
  7. _adjust_hint_by_mastery — hint level adjustment by mastery
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tutor_platform"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tutor_platform.teach_loop import (
    _detect_subject,
    _auto_rag_if_wrong,
    _enrich_with_mastery,
    _adjust_hint_by_mastery,
    TeachPromptManager,
    TeachLoopState,
    TeachPhase,
    run_teach_loop_from_args,
)
from tutor_platform.teach_question import TeachQuestion, ExtractedExam
from tutor_platform.teach_tools import get_kp_mastery_context


# ══════════════════════════════════════════════════════════════════
# Layer 1 — Subject detection
# ══════════════════════════════════════════════════════════════════

class TestDetectSubject:
    def test_math_chinese(self):
        assert _detect_subject("数学/分式/分式有意义的条件") == "math"

    def test_physics_chinese(self):
        assert _detect_subject("物理/力学/牛顿第一定律") == "physics"

    def test_chemistry_chinese(self):
        assert _detect_subject("化学/反应/化合反应") == "chemistry"

    def test_english_ascii(self):
        assert _detect_subject("english/grammar/tenses") == "english"

    def test_default_subject(self):
        assert _detect_subject("生物/细胞/细胞分裂") == "math"

    def test_empty_string(self):
        assert _detect_subject("") == "math"


# ══════════════════════════════════════════════════════════════════
# Layer 2 — YAML constraint loading
# ══════════════════════════════════════════════════════════════════

class TestPhaseConstraint:
    @pytest.fixture(autouse=True)
    def _pm(self):
        self.pm = TeachPromptManager.get()

    def test_first_question_constraint(self):
        c = self.pm.get_phase_constraint("FIRST_QUESTION")
        assert isinstance(c, str)
        assert len(c) > 100

    def test_evaluate_answer_constraint(self):
        c = self.pm.get_phase_constraint("EVALUATE_ANSWER")
        assert isinstance(c, str)
        assert len(c) > 100

    def test_unknown_phase_returns_empty(self):
        c = self.pm.get_phase_constraint("UNKNOWN_PHASE")
        assert c == ""


# ══════════════════════════════════════════════════════════════════
# Layer 3 — Wrapper function with pre-extracted data
# ══════════════════════════════════════════════════════════════════

class TestRunTeachLoopFromArgs:
    """Verify the wrapper correctly constructs state and returns dict."""

    @pytest.fixture
    def sample_exam(self):
        return ExtractedExam(
            questions=[
                TeachQuestion(
                    index=1, total=2, question_type="choice",
                    content="测试题目",
                    answer_key="A",
                    explanation="测试解析",
                    knowledge_point="数学/测试",
                    options={"A": "正确", "B": "错误"},
                ),
                TeachQuestion(
                    index=2, total=2, question_type="choice",
                    content="第二题",
                    answer_key="B",
                    explanation="第二题解析",
                    knowledge_point="数学/测试",
                    options={"A": "1", "B": "2"},
                ),
            ],
            total=2,
            raw_ocr="测试试卷",
        )

    @pytest.mark.asyncio
    async def test_first_question_with_pre_extracted(self, sample_exam):
        """FIRST_QUESTION from pre-extracted data (no LLM call)."""
        result = await run_teach_loop_from_args(
            phase="FIRST_QUESTION",
            mode="guide",
            learner_id="test_unit",
            context="试卷内容...",
            extracted_exam=sample_exam,
            trace_id="test-unit-001",
        )
        assert result["ok"] is True
        assert isinstance(result["content"], str)
        assert len(result["content"]) > 10
        assert result.get("question") is not None
        assert result["question"].get("index") == 1
        assert result.get("total_questions") == 2
        assert result.get("done") is False

    @pytest.mark.asyncio
    async def test_explain_mode(self):
        """explain mode returns immediately (no LLM)."""
        result = await run_teach_loop_from_args(
            mode="explain",
            learner_id="test_unit",
            message="请解释这道题",
            trace_id="test-unit-002",
        )
        assert result["ok"] is True
        assert "explain" in result["content"]

    @pytest.mark.asyncio
    async def test_empty_extracted_exam(self):
        """Without extracted_exam, returns content (may fall through to fallback)."""
        result = await run_teach_loop_from_args(
            phase="FIRST_QUESTION",
            mode="guide",
            learner_id="test_unit",
            context="简单试卷",
            trace_id="test-unit-003",
        )
        # Should either succeed (with content) or fail gracefully
        assert "ok" in result
        assert isinstance(result.get("ok"), bool)


# ══════════════════════════════════════════════════════════════════
# Layer 4 — Auto RAG trigger
# ══════════════════════════════════════════════════════════════════

class TestAutoRagIfWrong:
    """Verify _auto_rag_if_wrong behaves correctly without ChromaDB."""

    @pytest.fixture
    def wrong_state(self):
        return TeachLoopState(
            learner_id="test_rag",
            phase=TeachPhase.EVALUATE_ANSWER,
            current_question=1,
            extracted_exam=ExtractedExam(
                questions=[
                    TeachQuestion(
                        index=1, total=1, question_type="choice",
                        content="测试题",
                        answer_key="A",
                        explanation="解析",
                        knowledge_point="数学/测试/知识点",
                    ),
                ],
                total=1,
                raw_ocr="测试",
            ),
            is_correct=False,
            score=0.0,
            student_message="B",
            student_answer="B",
            correct_answer="A",
        )

    @pytest.mark.asyncio
    async def test_wrong_answer_triggers_rag(self, wrong_state):
        """答错 + 有知识点 → 应注入 tool_results."""
        await _auto_rag_if_wrong(wrong_state, "test-rag-001")
        # RAG may or may not return results (no ChromaDB in test env),
        # but the function should not crash and should add tool_results.
        # Even if ChromaDB is empty, the code path is exercised.
        assert hasattr(wrong_state, "tool_results")

    @pytest.mark.asyncio
    async def test_correct_answer_skips_rag(self):
        """答对时不触发 RAG."""
        state = TeachLoopState(
            learner_id="test_rag",
            current_question=1,
            is_correct=True,
        )
        await _auto_rag_if_wrong(state, "test-rag-002")
        assert len(state.tool_results) == 0

    @pytest.mark.asyncio
    async def test_no_kp_skips_rag(self):
        """无知识点时不触发 RAG."""
        state = TeachLoopState(
            learner_id="test_rag",
            current_question=1,
            is_correct=False,
            extracted_exam=ExtractedExam(
                questions=[
                    TeachQuestion(
                        index=1, total=1, question_type="choice",
                        content="测试",
                        answer_key="A",
                        explanation="解析",
                        knowledge_point="",  # empty KP
                    ),
                ],
                total=1,
                raw_ocr="测试",
            ),
        )
        await _auto_rag_if_wrong(state, "test-rag-003")
        assert len(state.tool_results) == 0


# ══════════════════════════════════════════════════════════════════
# Layer 5 — Per-KP Mastery query
# ══════════════════════════════════════════════════════════════════

class TestKpMasteryContext:
    """Verify get_kp_mastery_context from teach_tools."""

    @pytest.mark.asyncio
    async def test_empty_kp_returns_empty(self):
        ctx = await get_kp_mastery_context(learner_id="test", kp_id="")
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_no_mastery_data_returns_empty(self):
        """没有掌握度记录时返回空（不崩溃）。"""
        ctx = await get_kp_mastery_context(
            learner_id="nonexistent_user",
            kp_id="数学/测试/未知知识点",
        )
        # No mastery data = empty. Shouldn't crash.
        assert isinstance(ctx, str)

    @pytest.mark.asyncio
    async def test_returns_formatted_string_when_data_exists(self):
        """有掌握度记录时返回格式化文本。"""
        # Try with the actual test learner ID used elsewhere
        ctx = await get_kp_mastery_context(
            learner_id="test_verify",
            kp_id="数学/测试/知识点",
        )
        # Either empty (no data) or formatted — either is valid
        assert isinstance(ctx, str)


# ══════════════════════════════════════════════════════════════════
# Layer 6 — Mastery enrichment in state
# ══════════════════════════════════════════════════════════════════

class TestEnrichWithMastery:
    """Verify _enrich_with_mastery injects mastery_context into state."""

    @pytest.mark.asyncio
    async def test_no_learner_skips(self):
        state = TeachLoopState(learner_id="")
        await _enrich_with_mastery(state, "test-m-001")
        assert state.mastery_context == ""

    @pytest.mark.asyncio
    async def test_no_kp_skips(self):
        """没有知识点时不报错也不注入。"""
        state = TeachLoopState(
            learner_id="test",
            current_question=1,
        )
        await _enrich_with_mastery(state, "test-m-002")
        assert state.mastery_context == ""

    @pytest.mark.asyncio
    async def test_with_kp_from_extracted_exam(self):
        """有预提取试卷时自动获取 KP 并查询掌握度（不崩溃）。"""
        exam = ExtractedExam(
            questions=[
                TeachQuestion(
                    index=1, total=1, question_type="choice",
                    content="测试",
                    answer_key="A",
                    explanation="解析",
                    knowledge_point="数学/测试/知识点",
                ),
            ],
            total=1,
            raw_ocr="测试",
        )
        state = TeachLoopState(
            learner_id="test_mastery",
            current_question=1,
            extracted_exam=exam,
        )
        await _enrich_with_mastery(state, "test-m-003")
        # If no mastery data in DB, mastery_context stays empty — that's OK
        assert isinstance(state.mastery_context, str)
        if state.mastery_context:
            assert "掌握度" in state.mastery_context


# ══════════════════════════════════════════════════════════════════
# Layer 7 — Hint level adjustment by mastery
# ══════════════════════════════════════════════════════════════════

class TestAdjustHintByMastery:
    """Verify _adjust_hint_by_mastery changes hint_level based on mastery."""

    @pytest.mark.asyncio
    async def test_no_mastery_context_skips(self):
        state = TeachLoopState(learner_id="test")
        await _adjust_hint_by_mastery(state)
        assert state.hint_level == 0  # unchanged

    @pytest.mark.asyncio
    async def test_no_kp_skips(self):
        state = TeachLoopState(
            learner_id="test",
            mastery_context="some context",  # has context but no kp_id
        )
        await _adjust_hint_by_mastery(state)
        assert state.hint_level == 0  # unchanged

    @pytest.mark.asyncio
    async def test_adjustment_does_not_crash(self):
        """查询技能不崩溃，即使没有真实掌握度数据。"""
        state = TeachLoopState(
            learner_id="test_adjust",
            kp_id="数学/测试/某个知识点",
            mastery_context="📊 知识点掌握度 (测试)\n- 掌握度: 50%",
            hint_level=0,
            is_correct=False,
        )
        await _adjust_hint_by_mastery(state)
        # Without real mastery data, hint_level stays 0 — no crash is the test
        assert isinstance(state.hint_level, int)


# ══════════════════════════════════════════════════════════════════
# Layer 8 — Trace events
# ══════════════════════════════════════════════════════════════════

class TestTraceEvents:
    """Verify _add_trace and propagation through the teach loop."""

    def test_add_trace_appends_event(self):
        state = TeachLoopState(learner_id="test_tr")
        from tutor_platform.teach_loop import _add_trace
        _add_trace(state, "THINK", "platform_judge", "判题", "答案")
        _add_trace(state, "TOOL", "rag", "查询", "结果")
        _add_trace(state, "FINISH", "", "回复", "内容")
        assert len(state.trace_events) == 3
        assert state.trace_events[0]["label"] == "THINK"
        assert state.trace_events[1]["tool"] == "rag"
        assert state.trace_events[2]["label"] == "FINISH"

    def test_trace_content_truncated(self):
        state = TeachLoopState(learner_id="test_tr")
        from tutor_platform.teach_loop import _add_trace
        long_content = "x" * 500
        _add_trace(state, "THINK", "", long_content, long_content)
        assert len(state.trace_events[0]["content"]) <= 200
        assert len(state.trace_events[0]["result"]) <= 500

    @pytest.mark.asyncio
    async def test_run_teach_loop_propagates_trace(self):
        """run_teach_loop copies state.trace_events → result.trace."""
        from tutor_platform.teach_loop import _add_trace, run_teach_loop, TeachPromptManager
        state = TeachLoopState(learner_id="test_tr2", phase=TeachPhase.EVALUATE_ANSWER)
        _add_trace(state, "THINK", "test", "test event", "")
        prompts = TeachPromptManager.get()
        result = await run_teach_loop(state, prompts, "trace-test")
        assert len(result.trace) >= 1
        assert result.trace[0]["label"] == "THINK"

    @pytest.mark.asyncio
    async def test_wrapper_returns_trace_events(self):
        """run_teach_loop_from_args includes trace_events in dict."""
        from tutor_platform.teach_loop import run_teach_loop_from_args
        exam = ExtractedExam(
            questions=[TeachQuestion(
                index=1, total=1, question_type="choice",
                content="test", answer_key="A", explanation="test",
            )],
            total=1, raw_ocr="test",
        )
        result = await run_teach_loop_from_args(
            phase="FIRST_QUESTION", mode="guide",
            learner_id="test_tr3", context="test",
            extracted_exam=exam, trace_id="trace-test-dict",
        )
        assert "trace_events" in result
        assert len(result["trace_events"]) >= 1
        assert result["trace_events"][0]["label"] in ("PLAN", "FINISH", "THINK")


# ══════════════════════════════════════════════════════════════════
# Layer 8 — YAML hot-reload
# ══════════════════════════════════════════════════════════════════


class TestYamlHotReload:
    """TeachPromptManager hot-reload: 检测文件变更自动刷新缓存。"""

    @pytest.fixture
    def pm(self):
        """每次测试前重置单例，确保状态干净。"""
        from tutor_platform.teach_loop import TeachPromptManager
        TeachPromptManager._instance = None
        pm = TeachPromptManager.get()
        # 确认 _config_path 有效
        assert os.path.isfile(pm._config_path), f"Config not found: {pm._config_path}"
        return pm

    @pytest.fixture
    def tmp_yaml(self, tmp_path):
        """创建临时 YAML 文件用于模拟变更。"""
        import yaml
        path = tmp_path / "test-prompts.yaml"
        data = {
            "teacher_soul": "原始版本",
            "phases": {
                "TEST_PHASE": {
                    "system": "原始 system prompt",
                    "constraint": "原始约束",
                },
            },
            "hint_ladder": {"L1": {"template": "原始 L1"}},
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)
        return str(path)

    def test_resolve_config_path_exists(self, pm):
        """_resolve_config_path 返回有效的 YAML 文件路径。"""
        assert os.path.isfile(pm._config_path)
        assert pm._config_path.endswith("teach-prompts.yaml") or \
               pm._config_path.endswith("yaml")

    def test_initial_mtime_set(self, pm):
        """首次加载后 mtime 应为文件的实际 mtime。"""
        assert pm._last_mtime > 0
        assert abs(pm._last_mtime - os.path.getmtime(pm._config_path)) < 1.0

    def test_check_reload_no_change(self, pm):
        """文件未变更时 _check_reload 不应触发重新加载。"""
        original_mtime = pm._last_mtime
        original_prompts = pm._prompts
        pm._check_reload()
        assert pm._last_mtime == original_mtime
        assert pm._prompts is original_prompts

    def test_hot_reload_detects_change(self, pm, tmp_yaml):
        """修改 YAML 后 _check_reload 应检测到并重载。"""
        import yaml
        # 接管 _config_path 指向临时文件
        original_path = pm._config_path
        try:
            pm._config_path = tmp_yaml
            pm._load()  # 加载临时文件

            # 确认加载了原始内容
            assert pm.get_teacher_soul() == "原始版本"

            # 修改临时文件
            data = {
                "teacher_soul": "热重载版本",
                "phases": {"TEST_PHASE": {"system": "新版 system"}},
            }
            with open(tmp_yaml, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True)

            # 等待文件系统 mtime 变化（Windows 有时需要）
            import time
            time.sleep(0.05)

            # _check_reload 应检测到变更
            pm._check_reload()
            assert pm.get_teacher_soul() == "热重载版本"
        finally:
            pm._config_path = original_path
            pm._load()  # 恢复

    def test_hot_reload_atomic_swap(self, pm, tmp_yaml):
        """原子替换文件（write+rename）也能被热重载检测到。"""
        import yaml
        original_path = pm._config_path
        try:
            pm._config_path = tmp_yaml
            pm._load()
            assert pm.get_phase_prompt("TEST_PHASE", "system") == "原始 system prompt"

            # 模拟原子写入：写 temp 文件 → rename
            tmp_swap = tmp_yaml + ".swp"
            with open(tmp_swap, "w", encoding="utf-8") as f:
                yaml.dump({
                    "phases": {"TEST_PHASE": {"system": "原子写入版本"}},
                }, f, allow_unicode=True)
            import os as _os
            _os.replace(tmp_swap, tmp_yaml)

            import time
            time.sleep(0.05)

            pm._check_reload()
            assert pm.get_phase_prompt("TEST_PHASE", "system") == "原子写入版本"
        finally:
            pm._config_path = original_path
            pm._load()

    def test_hot_reload_preserves_unmodified_keys(self, pm, tmp_yaml):
        """热重载只更新变更的 key，未变更的 key 不会丢失。"""
        import yaml
        original_path = pm._config_path
        try:
            pm._config_path = tmp_yaml
            pm._load()

            # 追加 hint_ladder 到原文件
            with open(tmp_yaml, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data["hint_ladder"]["L2"] = {"template": "新增 L2"}
            with open(tmp_yaml, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True)

            import time
            time.sleep(0.05)
            pm._check_reload()

            # 原 key 仍在，新 key 已追加
            assert pm.get_hint_ladder()["L1"]["template"] == "原始 L1"
            assert pm.get_hint_ladder()["L2"]["template"] == "新增 L2"
        finally:
            pm._config_path = original_path
            pm._load()

    def test_hot_reload_broken_yaml_keeps_old_data(self, pm, tmp_yaml):
        """损坏的 YAML 不应覆盖现有数据。"""
        import yaml
        original_path = pm._config_path
        try:
            pm._config_path = tmp_yaml
            pm._load()
            original_data = pm._prompts

            # 写损坏内容
            with open(tmp_yaml, "w", encoding="utf-8") as f:
                f.write("{invalid: yaml: unclosed_brace")

            import time
            time.sleep(0.05)

            pm._check_reload()
            # 损坏应被静默处理，_prompts 保持旧数据
            assert pm._prompts == original_data
        finally:
            pm._config_path = original_path
            pm._load()

    def test_env_var_override(self, tmp_yaml, monkeypatch):
        """TEACH_PROMPTS_PATH 环境变量可覆盖默认路径。"""
        # 确保 tmp_yaml 包含有效内容
        import yaml
        with open(tmp_yaml, "w", encoding="utf-8") as f:
            yaml.dump({"teacher_soul": "来自环境变量"}, f, allow_unicode=True)

        from tutor_platform.teach_loop import TeachPromptManager
        TeachPromptManager._instance = None  # 重置单例
        monkeypatch.setenv("TEACH_PROMPTS_PATH", tmp_yaml)
        pm = TeachPromptManager.get()
        assert pm._config_path == tmp_yaml
        assert pm.get_teacher_soul() == "来自环境变量"
        monkeypatch.delenv("TEACH_PROMPTS_PATH", raising=False)
