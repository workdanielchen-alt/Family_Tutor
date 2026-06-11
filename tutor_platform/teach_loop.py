# teach_loop.py — 引导式教学 Agentic Loop 引擎
#
# 受 DeepTutor vendor 的 core/agentic/loop.py 启发，为逐题引导式教学
# 量身定制的简化版 Agentic Loop。支持 THINK → TOOL → FINISH 标签协议，
# 以及 Plan → Solve → Review 三阶段教学管道。
#
# 标签协议:
#   PLAN    — 出题阶段：分析题目特征，制定教学策略
#   THINK   — 思考阶段：分析学生答案，决定下一步行动
#   TOOL    — 工具调用：RAG查询 / 课程上下文 / 查看复习计划
#   SOLVE   — 执行教学：生成引导问题或讲解
#   REVIEW  — 复习总结：题目完成后知识点回顾
#   FINISH  — 终止：输出最终回复给用户
#
# 三阶段管道:
#   Phase 1 (PLAN):   分析题目 → 决定教学策略 → 准备变式题
#   Phase 2 (SOLVE):  学生答题 → 平台判题 → hint阶梯 → 评改
#   Phase 3 (REVIEW): 总结知识点 → 关联前置知识 → 建议复习

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional

import httpx

from tutor_platform.teach_question import (
    TeachQuestion,
    ExtractedExam,
    parse_teach_response,
    get_question_by_index,
    validate_question_against_exam,
    validate_evaluation_against_exam,
)
from tutor_platform.teach_tools import (
    rag_lookup,
    get_curriculum_kp_info,
    get_review_context,
    get_weak_points_context,
    get_kp_mastery_context,
)

logger = logging.getLogger(__name__)

# ── 标签定义 ──────────────────────────────────────────────────────


class TeachLabel(StrEnum):
    """教学循环中的合法标签"""
    PLAN = "PLAN"
    THINK = "THINK"
    TOOL = "TOOL"
    FINISH = "FINISH"
    REVIEW = "REVIEW"


# ── 教学阶段 ──────────────────────────────────────────────────────


class TeachPhase(StrEnum):
    """教学管道三阶段"""
    FIRST_QUESTION = "FIRST_QUESTION"    # Plan + 出第一题
    EVALUATE_ANSWER = "EVALUATE_ANSWER"  # Solve: 评改学生答案
    REVIEW_DONE = "REVIEW_DONE"          # Review: 全部完成后的总结


# ── 数据类 ────────────────────────────────────────────────────────


@dataclass
class TeachLoopState:
    """Agentic 教学循环的运行时状态"""
    learner_id: str
    teach_session_id: str = ""
    phase: TeachPhase = TeachPhase.FIRST_QUESTION
    current_question: int = 0
    total_questions: int = 0
    hint_level: int = 0
    consecutive_wrong: int = 0
    consecutive_correct: int = 0

    # 上下文
    exam_context: str = ""           # OCR试卷全文
    student_message: str = ""        # 学生当前消息
    student_answer: str = ""         # 学生当前答案
    correct_answer: str = ""         # 正确答案
    is_correct: Optional[bool] = None  # 平台判题结果
    score: float = 0.0

    # 预提取数据
    extracted_exam: Optional[ExtractedExam] = None

    # Plan 阶段产物
    plan_strategy: str = ""          # 教学策略描述
    plan_variations: list[str] = field(default_factory=list)  # 备选变式题

    # 工具调用结果
    tool_results: list[dict] = field(default_factory=list)

    # 掌握度信息
    kp_id: str = ""                    # 当前题目的知识点 ID
    mastery_context: str = ""          # 格式化的掌握度信息（注入 LLM 用）
    adaptive_action: str = ""          # 自适应教学指令（"skip_if_mastered" / "needs_review" / "more_hints" 等）

    # 输出
    final_content: str = ""

    # 元数据
    usage: dict[str, Any] = field(default_factory=dict)
    trace_events: list[dict] = field(default_factory=list)

    @property
    def should_use_hint(self) -> bool:
        """是否需要使用提示（答错时）"""
        return not self.is_correct if self.is_correct is not None else False

    @property
    def base_hint_level(self) -> int:
        """基础提示等级（0-3）"""
        if self.consecutive_wrong >= 3:
            return 3
        if self.consecutive_wrong >= 2:
            return 2
        if self.consecutive_wrong >= 1:
            return 1
        return 0

    @property
    def next_question_index(self) -> int:
        """下一题题号"""
        return self.current_question + 1


@dataclass
class TeachLoopResult:
    """教学循环的最终输出"""
    ok: bool = False
    content: str = ""
    phase: str = ""
    question: Optional[dict] = None
    evaluation: Optional[dict] = None
    current: int = 0
    total_questions: int = 0
    done: bool = False
    hint_level: int = 0
    error: str = ""
    trace: list[dict] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


# ── 提示管理器 ────────────────────────────────────────────────────


class TeachPromptManager:
    """从 YAML 加载教学提示模板，支持热重载（检测文件变更自动刷新）。

    首次加载后，每次 getter 调用都会检查 YAML 文件的 mtime，
    检测到变更时自动重新加载。生产环境修改 config/teach-prompts.yaml
    后无需重启进程。
    """

    _instance: Optional["TeachPromptManager"] = None
    _prompts: dict[str, Any] = {}
    _config_path: str = ""
    _last_mtime: float = 0.0
    _lock: threading.Lock = threading.Lock()

    def __init__(self):
        self._config_path = self._resolve_config_path()
        self._last_mtime = 0.0
        self._load()

    # ── 文件路径解析 ────────────────────────────────────────────────

    @staticmethod
    def _resolve_config_path() -> str:
        """定位 config/teach-prompts.yaml 的绝对路径。

        支持三种部署模式：
        1. 开发模式 (直接运行): tools/teach_loop.py → ../../config/teach-prompts.yaml
        2. Docker 平台容器: /tutor_platform/teach_loop.py → /app/config/teach-prompts.yaml
        3. 环境变量覆盖: TEACH_PROMPTS_PATH
        """
        env_path = os.getenv("TEACH_PROMPTS_PATH")
        if env_path:
            return env_path

        # 相对于当前文件 (tutor_platform/teach_loop.py → config/)
        file_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(file_dir, "..", "config", "teach-prompts.yaml"),
            # Docker: /tutor_platform/ → /app/config/
            os.path.join(file_dir, "..", "..", "app", "config", "teach-prompts.yaml"),
            os.path.join("/app", "config", "teach-prompts.yaml"),
        ]
        for cp in candidates:
            resolved = os.path.normpath(cp)
            if os.path.isfile(resolved):
                return resolved
        # fallback: 返回第一个候选路径（即使不存在，用于报错）
        return os.path.normpath(candidates[0])

    # ── 单例 ────────────────────────────────────────────────────────

    @classmethod
    def get(cls) -> "TeachPromptManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 加载与热重载 ────────────────────────────────────────────────

    def _load(self):
        """加载 config/teach-prompts.yaml 并记录 mtime。"""
        try:
            import yaml
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._prompts = yaml.safe_load(f) or {}
            self._last_mtime = os.path.getmtime(self._config_path)
            logger.info(
                "TeachPromptManager loaded %d top-level keys from %s (mtime=%s)",
                len(self._prompts), self._config_path, self._last_mtime,
            )
        except Exception as e:
            logger.warning("Failed to load teach-prompts.yaml: %s", e)
            self._prompts = {}

    def _check_reload(self):
        """检查文件 mtime，变更时自动热重载。

        轻量快速路径：先读 mtime（文件系统 stat，不耗 I/O），
        只有检测到变更才加锁重载。99.9% 的调用走快速路径。
        """
        try:
            current_mtime = os.path.getmtime(self._config_path)
        except OSError:
            return  # 文件暂时不可读，跳过本次检查

        if current_mtime <= self._last_mtime:
            return  # 快速路径：无变更

        # 检测到变更 → 加锁双检后重载
        # 双检模式 (double-checked locking) 避免并发线程同时重载
        with self._lock:
            # 另一个线程可能已经重载过了，再确认一次
            try:
                recheck_mtime = os.path.getmtime(self._config_path)
            except OSError:
                return
            if recheck_mtime <= self._last_mtime:
                return

            old_mtime = self._last_mtime
            import yaml
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._prompts = yaml.safe_load(f) or {}
                self._last_mtime = recheck_mtime
                logger.info(
                    "TeachPromptManager hot-reloaded (mtime: %s → %s, %d keys)",
                    old_mtime, recheck_mtime, len(self._prompts),
                )
            except Exception as e:
                logger.warning("TeachPromptManager hot-reload FAILED: %s", e)

    # ── 公共 getter（每个调用都先走 _check_reload）─────────────────

    def get_teacher_soul(self, mode: str = "guide") -> str:
        """获取教师人格提示词"""
        self._check_reload()
        section = self._prompts.get("teacher_soul", "")
        if isinstance(section, dict):
            return section.get(mode, section.get("guide", ""))
        # teacher_soul 是字符串 → guide 模式直接用
        if mode == "explain":
            return self._prompts.get("teacher_explain_soul", str(section))
        return str(section)

    def get_phase_prompt(self, phase: str, sub_key: str = "system") -> str:
        """获取阶段的提示词"""
        self._check_reload()
        phases = self._prompts.get("phases", {})
        phase_data = phases.get(phase, {})
        return phase_data.get(sub_key, "")

    def get_phase_constraint(self, phase: str) -> str:
        """获取阶段的 JSON 格式约束（constraint 子键）。

        DT WS 路径和 Direct DeepSeek 路径使用此约束确保 LLM
        输出严格 JSON 格式。YAML 中定义的约束是规范来源，
        优先使用，取不到时返回空字符串由调用者使用硬编码降级。
        """
        return self.get_phase_prompt(phase, "constraint")

    def get_json_schema_override(self) -> str:
        """获取 JSON Schema 覆盖指令"""
        self._check_reload()
        return self._prompts.get("json_schema_override", "")

    def get_hint_ladder(self) -> dict:
        """获取提示阶梯模板"""
        self._check_reload()
        return self._prompts.get("hint_ladder", {})

    def get_plan_review(self) -> dict:
        """获取 Plan/Review 阶段提示"""
        self._check_reload()
        return self._prompts.get("plan_review", {})

    def get_mastery_driven(self) -> dict:
        """获取掌握度驱动教学配置"""
        self._check_reload()
        return self._prompts.get("mastery_driven", {})

    def format(self, template: str, **kwargs) -> str:
        """用变量填充模板"""
        self._check_reload()
        try:
            return template.format(**kwargs)
        except KeyError as e:
            logger.warning("Missing template key: %s", e)
            return template
        except Exception as e:
            logger.warning("Template format error: %s", e)
            return template


# ── LLM 调用 ──────────────────────────────────────────────────────


async def _call_deepseek(
    system_prompt: str,
    user_prompt: str,
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    trace_id: str = "",
) -> tuple[str | None, dict]:
    """调用 DeepSeek API，返回 (content, usage)"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None, {}

    llm_url = "https://api.deepseek.com/v1/chat/completions"
    llm_model = model or os.getenv("LLM_MODEL", "deepseek-v4-flash")

    payload = {
        "model": llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    llm_url, json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code != 200:
                    logger.warning("[%s] _call_deepseek HTTP %d (attempt %d)", trace_id, resp.status_code, attempt + 1)
                    if attempt == 0:
                        await asyncio.sleep(1)
                    continue
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                if not content or len(content.strip()) < 10:
                    logger.warning("[%s] _call_deepseek short response (%d chars)", trace_id, len(content))
                    if attempt == 0:
                        await asyncio.sleep(1)
                    continue
                return content, usage
        except Exception as e:
            logger.warning("[%s] _call_deepseek failed (attempt %d): %s", trace_id, attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(1)
    return None, {}


# ── Agentic 教学循环核心 ───────────────────────────────────────────


async def run_teach_loop(
    state: TeachLoopState,
    prompts: TeachPromptManager | None = None,
    trace_id: str = "",
) -> TeachLoopResult:
    """执行一次教学循环（Plan → Solve → Review）。

    每次调用处理一个教学阶段：
    - FIRST_QUESTION: Plan + 出第一题
    - EVALUATE_ANSWER: Solve (评改 + 出下一题)
    - REVIEW_DONE: Review 总结

    替代原有的单体 _tutor_chat_core 核心逻辑。
    """
    if prompts is None:
        prompts = TeachPromptManager.get()

    result = TeachLoopResult()
    _t0 = time.time()

    logger.info(
        "[%s] run_teach_loop phase=%s learner=%s q=%d/%d",
        trace_id, state.phase, state.learner_id,
        state.current_question, state.total_questions,
    )

    # ── Phase 1: FIRST_QUESTION (Plan + 出第一题) ──────────────
    if state.phase == TeachPhase.FIRST_QUESTION:
        result = await _run_first_question(state, prompts, trace_id)

    # ── Phase 2: EVALUATE_ANSWER (Solve: 评改学生答案) ─────────
    elif state.phase == TeachPhase.EVALUATE_ANSWER:
        result = await _run_evaluate_answer(state, prompts, trace_id)

    # ── Phase 3: REVIEW_DONE (Review 总结) ─────────────────────
    elif state.phase == TeachPhase.REVIEW_DONE:
        result = await _run_review(state, prompts, trace_id)

    # 将 state 中的 trace_events 复制到 result（供前端展示）
    if state.trace_events:
        result.trace = list(state.trace_events)

    _elapsed = time.time() - _t0
    logger.info(
        "[%s] run_teach_loop done in %.2fs, ok=%s content_len=%d trace=%d",
        trace_id, _elapsed, result.ok, len(result.content), len(result.trace),
    )
    return result


async def _run_first_question(
    state: TeachLoopState,
    prompts: TeachPromptManager,
    trace_id: str,
) -> TeachLoopResult:
    """Phase 1: PLAN + 出第一题

    流程:
    1. PLAN: 分析试卷特征，制定教学策略
    2. 从预提取数据取第一题（失败则用 LLM 生成）
    3. 组装最终回复（题目 + 引导问题）
    """
    result = TeachLoopResult(phase="FIRST_QUESTION")

    # 设置题号为第1题
    state.current_question = 1

    # ── Step 1: 尝试用预提取数据出题 ──
    if state.extracted_exam and state.extracted_exam.questions:
        q1 = state.extracted_exam.questions[0]
        state.total_questions = state.extracted_exam.total

        # PLAN: 使用默认策略，跳过 LLM 调用（预提取数据已有完整题目信息）
        # _plan_step 是一次不必要的 DeepSeek API 调用，对出题质量提升有限
        # 却增加 2-3s 首题延迟。保留函数供需要时启用，默认用 'default'
        plan_strategy = "default"

        # 掌握度：预查第一题对应知识点的掌握情况
        await _enrich_with_mastery(state, trace_id)

        # 🆕 KB 注入: 出第一题时查教材参考
        state.kb_context = await _enrich_with_kb(state, trace_id)

        # Trace: PLAN 阶段
        _add_trace(state, "PLAN", "plan_strategy",
                   f"分析第1题 ({q1.question_type}, {q1.difficulty}, KP={q1.knowledge_point})",
                   f"策略: {plan_strategy} | 掌握度: {bool(state.mastery_context)}")

        # 组装第一题文本
        q1_text = _format_question_for_display(q1)
        guidance = _pick_guidance_question(q1, plan_strategy)

        # Trace: FINISH — 出题完成
        _add_trace(state, "FINISH", "",
                   f"出第1题 ({q1.question_type})",
                   q1_text[:200])

        result.ok = True
        result.content = q1_text
        if guidance:
            result.content += f"\n\n{guidance}"
        result.question = q1.to_dict()
        result.current = 1
        result.total_questions = state.total_questions
        result.done = False

        logger.info("[%s] FIRST_QUESTION from extracted exam (q1/%d, plan=%s)",
                     trace_id, state.total_questions, plan_strategy[:30] if plan_strategy else "none")
        return result

    # ── Step 2: 预提取数据不可用 → LLM 生成 ──
    # 构建 PLAN 阶段的 system prompt
    system_prompt = prompts.get_phase_prompt("FIRST_QUESTION", "system")
    if not system_prompt:
        system_prompt = _build_default_first_question_system(prompts)

    json_override = prompts.get_json_schema_override()
    if json_override:
        system_prompt = json_override + "\n" + system_prompt

    # 注入试卷上下文
    if state.exam_context:
        system_prompt += f"\n\n### 当前试卷内容\n{state.exam_context[:4000]}"

    # PLAN label 提示：先分析再出题
    plan_review = prompts.get_plan_review()
    plan_prompt = plan_review.get("plan_prompt", "")
    if plan_prompt:
        system_prompt += f"\n\n# 教学策略规划\n{plan_prompt}"

    system_prompt = prompts.format(system_prompt)


    user_prompt = prompts.get_phase_prompt("FIRST_QUESTION", "user_template")
    if not user_prompt:
        user_prompt = _build_default_first_question_user(state)

    user_prompt = prompts.format(user_prompt)
    if state.exam_context:
        user_prompt += f"\n{state.exam_context[:4000]}"

    content, usage = await _call_deepseek(system_prompt, user_prompt, trace_id=trace_id)
    result.usage = usage

    if content:
        result.ok = True
        result.content = content
        # 解析 JSON 获取题目信息
        parsed = parse_teach_response(content)
        if parsed and parsed.get("question"):
            q = parsed["question"]
            result.question = q
            result.total_questions = int(q.get("total", 0))
            result.current = 1
        result.done = False
        # Trace: FINISH — LLM 出题
        _add_trace(state, "FINISH", "deepseek",
                   f"LLM 生成第1题 ({result.total_questions}题)",
                   content[:200])
    else:
        result.ok = False
        result.error = "LLM returned empty response"

    return result


async def _run_evaluate_answer(
    state: TeachLoopState,
    prompts: TeachPromptManager,
    trace_id: str,
) -> TeachLoopResult:
    """Phase 2: SOLVE — 评估学生答案并出下一题

    核心流程 (Agentic Loop):
    1. THINK: 平台判题 → 分析答案 → 决定教学行动
    2. TOOL (可选): 答错时查询 RAG 获取知识点资料
    3. FINISH: 生成评改回复 + 下一题引导
    """
    result = TeachLoopResult(phase="EVALUATE_ANSWER")
    max_loop_iterations = 4  # 防止无限循环
    tool_used_this_turn = False

    # ── Step 0: 平台判题（精确，不依赖 LLM）──
    _platform_judge(state)
    # Trace: THINK — 平台判题结果
    if state.is_correct is not None:
        _status = "正确" if state.is_correct else "错误" if state.score == 0.0 else "部分正确"
        _add_trace(state, "THINK", "platform_judge",
                   f"平台判题: {_status} (得分 {state.score})",
                   f"学生答案: {state.student_answer} | 正确答案: {state.correct_answer}")

    # ── Step 0.5: 每题都查双库教材参考（答对给扩展，答错给精准参考）──
    await _enrich_with_kb(state, trace_id)

    # ── Step 0.6: 掌握度查询 — 了解学生对当前知识点的熟练度 ──
    await _enrich_with_mastery(state, trace_id)
    await _adjust_hint_by_mastery(state)
    if state.mastery_context:
        _add_trace(state, "THINK", "mastery",
                   f"掌握度分析: {state.kp_id}", state.mastery_context[:200])

    # ── Agentic Loop: THINK → TOOL → FINISH ──
    current_context = _build_eval_context(state)

    for iteration in range(max_loop_iterations):
        logger.info("[%s] Agentic loop iteration %d/%d", trace_id, iteration + 1, max_loop_iterations)

        # 构建 system prompt
        system_prompt = _build_agentic_system(state, prompts, iteration, tool_used_this_turn)

        # 调用 LLM
        content, usage = await _call_deepseek(
            system_prompt,
            current_context,
            temperature=0.7,
            trace_id=trace_id,
        )
        if usage:
            result.usage = {
                "prompt_tokens": result.usage.get("prompt_tokens", 0) + usage.get("prompt_tokens", 0),
                "completion_tokens": result.usage.get("completion_tokens", 0) + usage.get("completion_tokens", 0),
            }

        if not content:
            result.ok = False
            result.error = "LLM returned empty response in agentic loop"
            return result

        # 提取标签
        label = _extract_label(content)

        logger.info("[%s] Agentic label: %s (%d chars)", trace_id, label, len(content))

        if label == TeachLabel.FINISH:
            # Trace: FINISH — 生成教学回复
            _add_trace(state, "FINISH", "deepseek",
                       f"生成评改回复 (迭代 {iteration + 1}/{max_loop_iterations})",
                       content[:300])

            # 解析最终回复
            _final_text = _extract_label_content(content, TeachLabel.FINISH)
            if not _final_text:
                _final_text = content

            # 解析 JSON 结构化数据
            parsed = parse_teach_response(_final_text)
            if parsed:
                _eval = parsed.get("evaluation")
                _next_q = parsed.get("next_question")
                if _eval:
                    # 用预提取数据验证评估
                    if state.extracted_exam and state.extracted_exam.questions:
                        from tutor_platform.teach_question import validate_evaluation_against_exam
                        _ev = validate_evaluation_against_exam(
                            _eval, state.extracted_exam,
                            state.current_question, state.student_answer,
                        )
                        result.evaluation = {
                            "is_correct": _ev["is_correct"],
                            "score": _ev["score"],
                            "correct_answer": _ev["correct_answer"],
                            "feedback": _ev.get("feedback", ""),
                            "explanation": _ev.get("explanation", ""),
                            "knowledge_point": _ev.get("knowledge_point", ""),
                        }
                    else:
                        result.evaluation = _eval

                if _next_q:
                    result.question = _next_q
                    result.current = int(_next_q.get("index", state.next_question_index))
                    result.total_questions = int(_next_q.get("total", state.total_questions))

                result.done = (_next_q is None)

            result.ok = True
            result.content = _final_text
            result.hint_level = state.hint_level

            # 如果全部完成，附加 REVIEW 总结
            if result.done and not state.extracted_exam:
                # LLM 表态全部完成时才做 review
                pass

            return result

        elif label == TeachLabel.TOOL:
            # 提取工具调用指令
            tool_name, tool_args = _parse_tool_call(content)
            if tool_name:
                tool_result = await _execute_teach_tool(tool_name, tool_args, state)
                if tool_result:
                    tool_used_this_turn = True
                    state.tool_results.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": tool_result[:500],
                    })
                    _add_trace(state, "TOOL", tool_name,
                               f"工具调用: {tool_name} args={tool_args}",
                               tool_result[:300])
                    current_context = _append_tool_result(current_context, tool_name, tool_result)
                    continue  # 回到循环让 LLM 基于工具结果继续思考

            # 工具调用失败 → 降级到 FINISH
            logger.warning("[%s] TOOL call failed, falling through to FINISH", trace_id)

        elif label == TeachLabel.THINK:
            # Trace: THINK — LLM 推理步骤
            _add_trace(state, "THINK", "deepseek",
                       f"LLM 推理 (迭代 {iteration + 1}/{max_loop_iterations})",
                       _extract_label_content(content, TeachLabel.THINK)[:300])
            # THINK → 继续循环让 LLM 决定下一步
            current_context = _append_think_content(current_context, content)
            continue

    # 循环耗尽 → 强制生成最终回复
    _add_trace(state, "FINISH", "",
               f"Agentic Loop 耗尽 ({max_loop_iterations} 次)，强制结束",
               "")
    logger.warning("[%s] Agentic loop exhausted (%d iterations), forcing FINISH", trace_id, max_loop_iterations)
    return result


async def _run_review(
    state: TeachLoopState,
    prompts: TeachPromptManager,
    trace_id: str,
) -> TeachLoopResult:
    """Phase 3: REVIEW — 全部题目完成后的知识点总结"""
    result = TeachLoopResult(phase="REVIEW_DONE")

    system_prompt = prompts.get_plan_review().get("review_system", "")
    if not system_prompt:
        system_prompt = _build_default_review_system(prompts)

    user_prompt = f"本次教学已完成。请生成知识点总结。\n"
    if state.exam_context:
        user_prompt += f"\n试卷上下文：\n{state.exam_context[:2000]}"

    # 🆕 Review 阶段也注入 KB 上下文
    _kb = getattr(state, "kb_context", "")
    if _kb:
        user_prompt += f"\n\n教材参考：\n{_kb[:1500]}"

    content, usage = await _call_deepseek(system_prompt, user_prompt, trace_id=trace_id)
    result.usage = usage

    if content:
        result.ok = True
        result.content = content
        if _kb:
            result.content += f"\n\n## 📖 教材参考\n{_kb[:1200]}"
        result.done = True
    else:
        result.ok = False
        result.error = "Review generation failed"

    return result


# ── 平台判题 ──────────────────────────────────────────────────────


def _platform_judge(state: TeachLoopState) -> None:
    """平台侧精确判题：比较学生答案与正确答案"""
    if not state.student_message.strip() or not state.correct_answer:
        return

    from tutor_platform.rag.extractors import _match_answers, _match_answers_semantic

    student = state.student_message.strip()
    correct = state.correct_answer.strip()

    if _match_answers(student, correct):
        state.is_correct = True
        state.score = 1.0
        state.consecutive_correct += 1
        state.consecutive_wrong = 0
        state.hint_level = 0
    elif _match_answers_semantic(student, correct):
        state.is_correct = False  # 部分正确视为错
        state.score = 0.5
        state.consecutive_correct = 0
        state.consecutive_wrong += 1
        state.hint_level = min(state.base_hint_level, 3)
    else:
        state.is_correct = False
        state.score = 0.0
        state.consecutive_correct = 0
        state.consecutive_wrong += 1
        state.hint_level = min(state.base_hint_level, 3)

    state.student_answer = student


# ── 自动 RAG 查询（答错时触发）────────────────────────────────


def _detect_subject(kp_id: str) -> str:
    """从知识点ID（如"数学/分式/分式有意义的条件"）推断学科。"""
    kp_lower = kp_id.lower()
    if "数学" in kp_lower or "math" in kp_lower:
        return "math"
    if "物理" in kp_lower or "physics" in kp_lower:
        return "physics"
    if "化学" in kp_lower or "chemistry" in kp_lower:
        return "chemistry"
    if "英语" in kp_lower or "english" in kp_lower:
        return "english"
    return "math"


async def _enrich_with_kb(state: TeachLoopState, trace_id: str) -> str:
    """每道题都查询双库教材参考 (ChromaDB + DT LlamaIndex)。

    返回格式化的 KB 文本，供注入 LLM prompt。
    答案正确时提供扩展阅读，答错时提供精准教材参考。
    当 extracted_exam 不可用时，从 exam_context 中推断学科并直接搜索。
    """
    _kp_id = ""
    _subject = "math"
    _query_text = ""

    if state.extracted_exam:
        _q = get_question_by_index(state.extracted_exam, state.current_question)
        if _q and _q.knowledge_point:
            _kp_id = _q.knowledge_point
            _subject = _detect_subject(_q.knowledge_point)
            _query_text = _q.content or ""
            _top_k = 2 if state.is_correct else 5

    # Fallback: no extracted_exam — use exam context text directly
    if not _kp_id and state.exam_context:
        _ctx_lower = state.exam_context.lower()
        if "化学" in _ctx_lower:
            _subject = "chemistry"
        elif "物理" in _ctx_lower:
            _subject = "physics"
        elif "数学" in _ctx_lower:
            _subject = "math"
        _query_text = (state.student_message or "")[:300] or state.exam_context[:300]
        _kp_id = f"{_subject}/auto"
        _top_k = 3

    if not _kp_id:
        return ""

    try:
        _chroma_result = await rag_lookup(
            kp_id=_kp_id,
            subject=_subject,
            query_text=_query_text,
        )
        from tutor_platform.teach_tools import rag_dt_lookup
        _dt_result = await rag_dt_lookup(
            kp_id=_kp_id,
            query_text=_query_text,
            top_k=_top_k,
        )

        _parts: list[str] = []
        if _chroma_result:
            _parts.append("### 教学摘要\n" + _chroma_result)
        if _dt_result:
            _parts.append("### 教材原文\n" + _dt_result)
        _kb_text = "\n\n".join(_parts) if _parts else ""

        if _kb_text:
            _label = "扩展阅读" if state.is_correct else "精准教材参考"
            if not state.extracted_exam:
                _label = "教材参考"
            state.tool_results.append({
                "tool": "rag_lookup",
                "args": {"kp_id": _kp_id, "label": _label},
                "result": _kb_text[:800],
            })
            _add_trace(state, "TOOL", "rag_lookup",
                       f"📖 {_label}: {_kp_id}", _kb_text[:300])
            # Store clean KB content on state (system prompt builder uses it)
            state.kb_context = (
                f"### {_label}\n{_kb_text}"
            )
            logger.info("[%s] KB context injected for %s (%s, %d chars)",
                        trace_id, _kp_id, _label, len(_kb_text))
        return _kb_text
    except Exception as e:
        logger.debug("[%s] KB enrichment failed (non-fatal): %s", trace_id, e)
        return ""


# ── Trace 事件辅助 ─────────────────────────────────────────────


def _add_trace(
    state: TeachLoopState,
    label: str,
    tool: str = "",
    content: str = "",
    result_text: str = "",
) -> None:
    """追加一条 trace 事件到 state.trace_events.

    Args:
        label: THINK / TOOL / FINISH / PLAN / REVIEW
        tool: 工具名（TOOL 阶段用）
        content: 事件描述或生成内容（前 200 字）
        result_text: 工具结果或详细输出（前 500 字）
    """
    state.trace_events.append({
        "label": label,
        "tool": tool,
        "content": content[:200],
        "result": result_text[:500],
    })


# ── 掌握度查询与注入 ──────────────────────────────────────────


async def _enrich_with_mastery(state: TeachLoopState, trace_id: str) -> None:
    """查询当前知识点掌握度并注入 state.mastery_context。

    在每道题开始教学前调用，让 LLM 了解学生对当前知识点的掌握水平，
    从而调整提示深度和教学策略。不阻塞流程——失败时静默跳过。
    """
    if not state.learner_id:
        return

    # 尝试从预提取试卷获取当前题目的 KP
    _kp = state.kp_id
    if not _kp and state.extracted_exam:
        try:
            _q = get_question_by_index(state.extracted_exam, state.current_question)
            if _q and _q.knowledge_point:
                _kp = _q.knowledge_point
                state.kp_id = _kp
        except Exception:
            pass

    if not _kp:
        return

    try:
        _ctx = await get_kp_mastery_context(state.learner_id, _kp)
        if _ctx:
            state.mastery_context = _ctx
            logger.info("[%s] Mastery context injected for %s (level=%s)",
                        trace_id, _kp,
                        [line for line in _ctx.split("\n") if "掌握度" in line])
    except Exception as e:
        logger.debug("[%s] Mastery enrichment failed (non-fatal): %s", trace_id, e)


async def _adjust_hint_by_mastery(state: TeachLoopState) -> None:
    """根据掌握度和答题表现自适应调整教学策略。

    答题前调整:
      - 掌握度 <30% + 已答 ≥2 题 → 薄弱，初始 hint_level=1
      - 掌握度 ≥80% + 已答 ≥3 题 → 掌握好，减少提示

    答题后决策:
      - 连续答对 3 题 + 掌握度 ≥70% → 建议跳过同类题
      - 连续答错 2 题 → 建议重点巩固
      - 连续答错 3 题 → 直接给完整解析
    """
    state.adaptive_action = ""
    _mastery_level = -1.0
    _mastery_total = 0

    # 查掌握度（只需一次）
    if state.kp_id:
        try:
            from domains.tutoring.mastery import get_mastery
            _md = await asyncio.to_thread(get_mastery, state.learner_id, state.kp_id)
            if _md and isinstance(_md, dict):
                _mastery_level = _md.get("level", 0.0)
                _mastery_total = _md.get("total", 0)
        except Exception:
            pass

    # ── 连续答对 3+ 题 + 掌握度足够 → 建议跳过 ──
    if state.consecutive_correct >= 3 and _mastery_level >= 0.7:
        state.adaptive_action = "skip_if_mastered"
        state.hint_level = max(0, state.hint_level - 1)
        logger.info("[mastery] %d consecutive correct, mastery=%.0f%%, suggest skip",
                    state.consecutive_correct, _mastery_level * 100)
        _add_trace(state, "THINK", "mastery_adapt",
                   f"连续答对 {state.consecutive_correct} 题 (掌握 {_mastery_level*100:.0f}%)，建议跳过同类题", "")
        return

    # ── 连续答错 3+ 题 → 直接完整解析 ──
    if state.consecutive_wrong >= 3:
        state.adaptive_action = "full_explain"
        state.hint_level = 3
        logger.info("[mastery] %d consecutive wrong, forcing full explain", state.consecutive_wrong)
        _add_trace(state, "THINK", "mastery_adapt",
                   f"连续答错 {state.consecutive_wrong} 次，直接给出完整解析", "")
        return

    # ── 连续答错 2 题 → 提升 hint 等级 ──
    if state.consecutive_wrong >= 2:
        state.adaptive_action = "needs_review"
        if state.hint_level < 2:
            state.hint_level = 2
        logger.info("[mastery] %d consecutive wrong, setting hint_level=%d",
                    state.consecutive_wrong, state.hint_level)
        _add_trace(state, "THINK", "mastery_adapt",
                   f"连续答错 {state.consecutive_wrong} 次，提示等级 {state.hint_level}", "")
        return

    # ── 基于历史掌握度调整初始 hint ──
    if _mastery_level < 0:
        return

    if _mastery_level < 0.3 and _mastery_total >= 2 and state.hint_level == 0:
        state.hint_level = 1
        state.adaptive_action = "more_hints"
        _add_trace(state, "THINK", "mastery_adapt",
                   f"掌握度 {_mastery_level*100:.0f}% 较低，提示等级=1", "")
        logger.info("[mastery] Low mastery (%.0f%%), bumped hint_level to 1", _mastery_level * 100)
    elif _mastery_level >= 0.8 and _mastery_total >= 3 and state.is_correct is False and state.hint_level > 0:
        state.hint_level = max(0, state.hint_level - 1)
        _add_trace(state, "THINK", "mastery_adapt",
                   f"掌握度 {_mastery_level*100:.0f}% 较高，降低提示到 {state.hint_level}", "")
        logger.info("[mastery] High mastery (%.0f%%), reduced hint_level to %d",
                    _mastery_level * 100, state.hint_level)


# ── PLAN 步骤 ─────────────────────────────────────────────────────


async def _plan_step(
    state: TeachLoopState,
    question: TeachQuestion,
    prompts: TeachPromptManager,
    trace_id: str,
) -> str:
    """PLAN: 分析题目，制定教学策略（轻量 LLM 调用）"""
    plan_config = prompts.get_plan_review()
    plan_template = plan_config.get("plan_prompt", "")

    if not plan_template:
        return "default"

    user = prompts.format(
        plan_template,
        index=question.index,
        total=question.total,
        question_type=question.question_type,
        content=question.content[:500],
        difficulty=question.difficulty,
        knowledge_point=question.knowledge_point,
    )

    system = "你是一个教学策略分析师。用一句话总结最佳教学策略。只输出策略名称。"
    content, _ = await _call_deepseek(system, user, max_tokens=100, trace_id=trace_id)
    return (content or "default").strip()


# ── Label 解析 ────────────────────────────────────────────────────


def _extract_label(content: str) -> Optional[TeachLabel]:
    """从 LLM 回复中提取标签"""
    if not content:
        return None

    # 匹配模式: ### LABEL, **LABEL**, [LABEL], LABEL:
    for label in TeachLabel:
        patterns = [
            rf"(?:^|\n)\s*#{{1,3}}\s*{label.value}\s*(?:\n|$)",
            rf"(?:^|\n)\s*\*\*{label.value}\*\*\s*(?:\n|$)",
            rf"(?:^|\n)\s*\[{label.value}\]\s*(?:\n|$)",
            rf"(?:^|\n)\s*{label.value}:\s*(?:\n|$)",
        ]
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                return label

    # 没有标签但有内容 → 默认 FINISH
    if len(content.strip()) >= 20:
        return TeachLabel.FINISH
    return None


def _extract_label_content(content: str, label: TeachLabel) -> str:
    """提取标签后的内容（去除标签行）"""
    lines = content.split("\n")
    result_lines = []
    skip_label = True
    for line in lines:
        stripped = line.strip()
        if skip_label:
            if re.search(rf"(?:#{{1,3}}\s*|\*\*|\[|\b){label.value}(?:\s*\*\*|\]|:|$)", stripped, re.IGNORECASE):
                skip_label = False
                continue
        result_lines.append(line)

    return "\n".join(result_lines).strip()


def _parse_tool_call(content: str) -> tuple[Optional[str], dict]:
    """解析 TOOL label 中的工具调用"""
    tool_name = None
    tool_args = {}

    # 提取工具名
    for tool_key in ("rag", "curriculum", "review", "weak_points",
                     "geogebra", "funcplot", "numberline"):
        if tool_key in content.lower():
            tool_name = tool_key
            break

    if not tool_name:
        return None, {}

    # 提取参数
    kp_match = re.search(r"kp_id[=:]\s*['\"]?([^'\"\s,]+)", content, re.IGNORECASE)
    if kp_match:
        tool_args["kp_id"] = kp_match.group(1)

    subject_match = re.search(r"subject[=:]\s*['\"]?([^'\"\s,]+)", content, re.IGNORECASE)
    if subject_match:
        tool_args["subject"] = subject_match.group(1)

    query_match = re.search(r"query[=:]\s*['\"]?([^'\"]+)", content, re.IGNORECASE)
    if query_match:
        tool_args["query_text"] = query_match.group(1).strip()

    return tool_name, tool_args


async def _execute_teach_tool(tool_name: str, args: dict, state: TeachLoopState) -> str:
    """执行教学工具"""
    try:
        if tool_name == "rag":
            return await rag_lookup(
                kp_id=args.get("kp_id", ""),
                subject=args.get("subject", "math"),
                query_text=args.get("query_text", ""),
            )
        elif tool_name == "curriculum":
            return get_curriculum_kp_info(
                kp_id=args.get("kp_id", ""),
                subject=args.get("subject", "math"),
            )
        elif tool_name == "review":
            return await get_review_context(state.learner_id)
        elif tool_name == "weak_points":
            return await get_weak_points_context(state.learner_id)
    except Exception as e:
        logger.warning("Tool %s failed: %s", tool_name, e)
        return f"[TOOL_ERROR] {tool_name}: {e}"

    return ""


# ── Context 构建辅助 ──────────────────────────────────────────────


def _build_eval_context(state: TeachLoopState) -> str:
    """构建 EVALUATE_ANSWER 阶段的用户 prompt context"""
    parts = []

    # 平台判题结果
    if state.is_correct is not None:
        status = "✅ 正确" if state.is_correct else "❌ 错误" if state.score == 0.0 else "⚠️ 部分正确"
        parts.append(f"## 平台判题结果\n{status}\n正确答案: {state.correct_answer}\n学生答案: {state.student_answer}")

    # 当前题目
    parts.append(f"## 当前题目 (第{state.current_question}题)")
    parts.append(state.student_message[:500] if state.student_message else state.exam_context[:500])

    # 提示等级
    parts.append(f"## 教学参数\nhint_level={state.hint_level} consecutive_wrong={state.consecutive_wrong}")

    # 工具结果
    if state.tool_results:
        parts.append("## 之前的工具查询结果")
        for tr in state.tool_results[-2:]:  # 只保留最近2次
            parts.append(f"- [{tr['tool']}]: {tr['result'][:300]}")

    # 掌握度信息
    if state.mastery_context:
        parts.append(state.mastery_context)

    # KB context is appended directly to result.content — not needed in eval context

    return "\n\n".join(parts)


def _build_agentic_system(
    state: TeachLoopState,
    prompts: TeachPromptManager,
    iteration: int,
    tool_used: bool,
) -> str:
    """构建 Agentic Loop 的 system prompt。

    以 SOUL.md 教学人格为基础（含 KB 参考/课程大纲/掌握度/复习提醒），
    叠加 agentic loop 的标签协议。让 LLM 在苏格拉底引导式教学中
    自然地引用教材知识，而非机械 dump 教材原文。
    """
    # ── 基础人格：从 SOUL.md 中获取（_build_teaching_persona 已注入 KB 参考）──
    _teacher_soul = prompts.get_teacher_soul("guide")
    _base = _teacher_soul or _build_default_eval_system(prompts)

    # ── JSON schema ──
    system = _base
    json_override = prompts.get_json_schema_override()
    if json_override:
        system = json_override + "\n" + system

    # ── 标签协议 ──
    label_protocol = (
        "\n\n# 🏷️ 输出协议\n\n"
        "你是一位苏格拉底式引导教师。回复第一行必须写以下标签之一：\n\n"
        "### THINK — 思考\n"
        "分析学生回答，判断：是否需要查教材原文来更好地解释？"
        " 是否需要知识库来补充背景？是否需要可视化工具？\n\n"
        "### TOOL — 查阅参考资料\n"
        "格式: TOOL tool_name kp_id=xxx subject=xxx\n"
        "可用工具:\n"
        "- rag: 教材教学摘要 (适合查概念定义/知识点说明)\n"
        "- rag_dt: 教材PDF原文 (适合查精确公式/图表)\n"
        "- curriculum: 课程章节大纲\n"
        "- review: 到期复习项\n"
        "- weak_points: 薄弱知识点\n"
        "- geogebra/funcplot/numberline: 可视化数学工具\n\n"
        "### FINISH — 给出教学回复\n"
        "JSON 格式，含评改结果和下题。引用教材时自然融入，如「根据教材…」。\n\n"
        "🔴 每轮一个标签。THINK→TOOL→FINISH 序。TOOL 后必 FINISH。\n"
        "🔴 当教材参考中已有该知识点的教学摘要时，优先用摘要讲解；\n"
        "   如需精确公式或原图，再调用 rag_dt 查 PDF 原文。\n"
    )

    if tool_used:
        label_protocol += "\n## ⚠️ 已调用工具，本轮必须直接输出 FINISH\n"

    system += label_protocol

    # ── 教材参考 (每题自动查询) ──
    # 注入系统提示供 LLM 自然引用，而非 dump 给学生
    _kb = getattr(state, "kb_context", "")
    if _kb:
        system += "\n\n## 📖 教材参考资料（可引用，勿全文复制给学生）\n"
        system += "以下是从教材中自动检索的相关内容。讲解时如涉及相关知识点，"
        system += "请自然地引用（如「根据教材，…」），不要机械复制原文。\n\n"
        system += _kb[:2000]

    # ── 教学策略 ──
    if state.plan_strategy:
        system += f"\n\n## 当前教学策略: {state.plan_strategy}"

    # ── 掌握度 ──
    if state.mastery_context:
        system += f"\n\n{state.mastery_context}"

    # ── 自适应教学 ──
    if state.adaptive_action:
        _action_hint = {
            "skip_if_mastered": "该生已多次答对该知识点，掌握度>70%。如再次答对，简洁确认即可，不需展开。",
            "needs_review": "该生已连续答错2次+，需重点巩固。给出正确答案后补充基础概念和相关例题。",
            "full_explain": "该生已连续答错3次+，直接给出完整解题过程，不需再提问。",
            "more_hints": "该生掌握度低，给更详细的引导和提示。",
        }
        _hint = _action_hint.get(state.adaptive_action, "")
        if _hint:
            system += f"\n\n## 📋 自适应指令\n{_hint}"

    return system


def _append_tool_result(context: str, tool_name: str, tool_result: str) -> str:
    """将工具结果追加到 context"""
    return context + f"\n\n## [{tool_name}] 工具查询结果\n{tool_result[:1000]}\n\n请基于以上信息继续。"


def _append_think_content(context: str, think_content: str) -> str:
    """将 THINK 内容追加到 context"""
    think_text = _extract_label_content(think_content, TeachLabel.THINK)
    if think_text:
        return context + f"\n\n## 思考: {think_text[:500]}"
    return context


# ── 默认 Prompt 构建 (当 YAML 不可用时的降级) ─────────────────────


def _build_default_first_question_system(prompts: TeachPromptManager) -> str:
    """YAML 不可用时的降级 system prompt"""
    return prompts.get_teacher_soul("guide")


def _build_default_first_question_user(state: TeachLoopState) -> str:
    """YAML 不可用时的降级 user prompt"""
    return f"[PHASE:FIRST_QUESTION]\n{state.exam_context[:4000]}"


def _build_default_eval_system(prompts: TeachPromptManager) -> str:
    """降级 EVALUATE_ANSWER system prompt"""
    return prompts.get_teacher_soul("guide")


def _build_default_review_system(prompts: TeachPromptManager) -> str:
    """降级 REVIEW system prompt"""
    return "你是一位教学总结专家。请为刚刚完成的教学生成一份知识点回顾总结。"


# ── 题目显示辅助 ──────────────────────────────────────────────────


def _format_question_for_display(q: TeachQuestion) -> str:
    """将 TeachQuestion 格式化为可显示文本"""
    lines = [f"第{q.index}题"]

    if q.question_type == "choice" and q.options:
        lines.append(q.content)
        for k, v in q.options.items():
            lines.append(f"{k}. {v}")
    else:
        lines.append(q.content)

    return "\n".join(lines)


def _pick_guidance_question(q: TeachQuestion, strategy: str) -> str:
    """根据题目类型和教学策略选择合适的引导问题"""
    if not q.hints or len(q.hints) == 0:
        # 生成默认引导问题
        if q.question_type == "choice":
            return "先思考一下：这道题考的是哪个知识点？"
        elif q.question_type == "fill_blank":
            return "想一想，需要用到什么公式或概念来解答？"
        else:
            return "先说说你的解题思路吧？"

    # 优先使用 L1（概念引导，不问答案）
    return q.hints[0] if q.hints[0] else "这道题考的是哪个知识点？"


# ═══════════════════════════════════════════════════════════════════
# 对外包装函数 — 供 _tutor_chat_core 调用
# ═══════════════════════════════════════════════════════════════════


async def run_teach_loop_from_args(
    phase: str = "",
    learner_id: str = "",
    context: str = "",
    message: str = "",
    mode: str = "guide",
    trace_id: str = "",
    teach_session_id: str = "",
    extracted_exam: ExtractedExam | None = None,
    answer_keys: dict | None = None,
    last_question_num: int = 0,
    persona: str | None = None,
) -> dict:
    """从 keyword args 构造 TeachLoopState 并调用 run_teach_loop().

    这是 _tutor_chat_core 与 run_teach_loop 之间的适配层。
    将 dict 风格的 keyword args 转为 TeachLoopState 和 TeachLoopResult，
    使其匹配 provider_api.py 的调用约定。

    Returns:
        dict 包含:
            ok (bool): 是否成功
            content (str): 教学回复文本
            error (str): 失败时的错误信息（可选）
            question (dict): 当前/下一题的数据（可选）
            evaluation (dict): 评改数据（可选）
            current (int): 当前题号
            total_questions (int): 总题数
            hint_level (int): 当前提示等级
    """
    _answer_keys = answer_keys or {}

    # 从 answer_keys 获取当前题目的正确答案
    _correct_answer = _answer_keys.get(last_question_num, "")

    # 将 phase str → TeachPhase enum
    try:
        _teach_phase = TeachPhase(phase) if phase else TeachPhase.FIRST_QUESTION
    except ValueError:
        logger.warning("[%s] Unknown phase %r, defaulting to FIRST_QUESTION", trace_id, phase)
        _teach_phase = TeachPhase.FIRST_QUESTION

    state = TeachLoopState(
        learner_id=learner_id,
        teach_session_id=teach_session_id,
        phase=_teach_phase,
        current_question=last_question_num,
        total_questions=extracted_exam.total if extracted_exam else 0,
        exam_context=context,
        student_message=message,
        student_answer=message,
        correct_answer=_correct_answer,
        extracted_exam=extracted_exam,
    )

    # 如果是 explain 模式，不走 Agentic Loop
    if mode != "guide":
        _prompts = TeachPromptManager.get()
        _teacher_soul = _prompts.get_teacher_soul(mode)
        return {
            "ok": True,
            "content": f"[{mode} mode] {message[:200]}",
            "error": "",
        }

    result = await run_teach_loop(
        state=state,
        prompts=None,  # 使用默认 TeachPromptManager 单例
        trace_id=trace_id,
    )

    return {
        "ok": result.ok,
        "content": result.content,
        "error": result.error,
        "question": result.question,
        "evaluation": result.evaluation,
        "current": result.current,
        "total_questions": result.total_questions,
        "hint_level": result.hint_level,
        "done": result.done,
        "trace_events": result.trace,
    }
