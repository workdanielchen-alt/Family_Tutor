"""TeachQuestion — Structured question model for guided teaching.

Replaces the legacy free-text LLM output with a strict JSON schema that
the frontend can render as interactive quiz cards (choice buttons, fill-blank
inputs, hint panels, celebration animations).

Also defines TeachEvaluation for per-answer grading results and the shared
JSON extraction / validation utilities used by _tutor_chat_core.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Optional

# ── Data models ───────────────────────────────────────────────────────────────


@dataclass
class TeachQuestion:
    """A single structured question for the guided-teaching flow.

    LLM is instructed to output this shape inside a ```json code block
    so the platform can parse it deterministically instead of relying on
    regex heuristics against free text.
    """

    index: int                      # 1-based question number within the paper
    total: int                      # total questions in the paper
    question_type: str              # "choice" | "fill_blank" | "short_answer" | "written"
    content: str                    # Markdown question body (may contain LaTeX)
    answer_key: str                 # correct answer (A/B/C/D for choice, text otherwise)
    explanation: str                # step-by-step solution
    knowledge_point: str = ""       # "学科/章/节"
    hints: list[str] = field(default_factory=list)  # [L1, L2, L3] progressive hints
    difficulty: str = "medium"      # "easy" | "medium" | "hard"
    options: Optional[dict[str, str]] = None  # {"A": "...", "B": "..."} — choice only

    # ── Validation ────────────────────────────────────────────────────────

    _REQUIRED_FIELDS = ("index", "total", "question_type", "content",
                        "answer_key", "explanation")
    _VALID_TYPES = ("choice", "fill_blank", "short_answer", "written")
    _VALID_DIFFICULTIES = ("easy", "medium", "hard")

    def validate(self) -> list[str]:
        """Return list of validation error messages (empty = valid)."""
        errs: list[str] = []
        for f in self._REQUIRED_FIELDS:
            val = getattr(self, f, None)
            if val is None or (isinstance(val, str) and not val.strip()):
                errs.append(f"Missing required field: {f}")
        if self.question_type not in self._VALID_TYPES:
            errs.append(f"Invalid question_type {self.question_type!r} — "
                        f"must be one of {self._VALID_TYPES}")
        if self.difficulty not in self._VALID_DIFFICULTIES:
            errs.append(f"Invalid difficulty {self.difficulty!r} — "
                        f"must be one of {self._VALID_DIFFICULTIES}")
        if self.question_type == "choice" and not self.options:
            errs.append("Choice question must have options")
        if isinstance(self.total, int) and self.index > self.total:
            errs.append(f"index={self.index} exceeds total={self.total}")
        if isinstance(self.index, int) and self.index < 1:
            errs.append(f"index={self.index} must be >= 1")
        if not isinstance(self.hints, list):
            errs.append("hints must be a list")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TeachQuestion":
        """Construct from parsed JSON dict, filling defaults for missing optional fields."""
        content = str(d.get("content", ""))
        # Strip option text from content — LLM sometimes includes
        # "A. xxx B. yyy" in content even though options is a separate field.
        content = strip_options_from_content(content)
        return cls(
            index=int(d.get("index", 0)),
            total=int(d.get("total", 0)),
            question_type=str(d.get("question_type", "short_answer")),
            content=content,
            answer_key=str(d.get("answer_key", "")),
            explanation=str(d.get("explanation", "")),
            knowledge_point=str(d.get("knowledge_point", "")),
            hints=_ensure_str_list(d.get("hints", [])),
            difficulty=str(d.get("difficulty", "medium")),
            options=_parse_options(d.get("options")),
        )


@dataclass
class TeachEvaluation:
    """Grading result for one student answer."""

    is_correct: bool
    score: float                    # 0.0 | 0.5 | 1.0
    feedback: str                   # encouraging / corrective message
    answer_key: str                 # correct answer for display
    explanation: str                # step-by-step solution (shown on wrong)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TeachEvaluation":
        return cls(
            is_correct=bool(d.get("is_correct", False)),
            score=float(d.get("score", 0.0)),
            feedback=str(d.get("feedback", "")),
            answer_key=str(d.get("answer_key", "")),
            explanation=str(d.get("explanation", "")),
        )


@dataclass
class KnowledgeSummary:
    """Per-knowledge-point stats for the completion panel."""
    correct: int
    total: int

    @property
    def rate(self) -> float:
        return self.correct / max(self.total, 1)

    def to_dict(self) -> dict:
        return {"correct": self.correct, "total": self.total}


# ── JSON extraction & validation ─────────────────────────────────────────────


def _ensure_str_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(v) for v in val]


def _parse_options(val: Any) -> Optional[dict[str, str]]:
    if not isinstance(val, dict):
        return None
    result = {str(k): str(v) for k, v in val.items()}
    return result if result else None


# ── Content cleaning ───────────────────────────────────────────────────────

_OPTION_PREFIX_RE = re.compile(r"^[A-F][\.．、\s]\s*", re.UNICODE)
# Matches an option start mid-line: one or more spaces/newline then A.-D.
_INLINE_OPTION_RE = re.compile(r"[\s\n]+[A-F][\.．、\s]\s+\S", re.UNICODE)


def strip_options_from_content(content: str) -> str:
    """Remove option text from question content.

    Handles both formats LLMs produce:
    - Options on their own lines: strips trailing "A. xxx" lines
    - Options inline: strips from the first "A." occurrence onward
    """
    lines = content.split("\n")
    result_lines: list[str] = []

    for line in lines:
        s = line.strip()
        # Does this line start with an option prefix (A.-F.)?
        if _OPTION_PREFIX_RE.match(s):
            # Found option block — stop here and discard remaining
            break
        # Does this line contain an inline option start?
        m = _INLINE_OPTION_RE.search(line)
        if m:
            # Keep text before the first option
            result_lines.append(line[: m.start()].rstrip())
            break
        result_lines.append(line)

    result = "\n".join(result_lines).strip()
    return result or content  # fallback: return original if empty


# Regex to extract the LAST ```json ... ``` code block from LLM output.
# We use findall and take the last match because the LLM sometimes embeds
# example JSON blocks in earlier text.
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


def extract_json_block(text: str) -> Optional[str]:
    """Return the raw JSON string from the last ```json ... ``` block in *text*."""
    matches = JSON_BLOCK_RE.findall(text)
    if not matches:
        # Try bare JSON (no code fence) as a fallback — some models skip fences.
        # Look for a line starting with { and ending with } at the very end.
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return stripped
        return None
    return matches[-1].strip()


def parse_teach_response(text: str) -> Optional[dict]:
    """Extract and parse the JSON block from an LLM teach response.

    Returns the parsed dict on success, or None if no valid JSON found.
    The caller should retry (with a nudge) on None.
    """
    raw = extract_json_block(text)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def parse_question_from_json(parsed: dict) -> Optional[TeachQuestion]:
    """Extract a TeachQuestion from a parsed teach JSON response.

    Supports two shapes:
      - FIRST_QUESTION: {"phase": "FIRST_QUESTION", "question": {...}}
      - EVALUATE_ANSWER: {"phase": "EVALUATE_ANSWER", ..., "next_question": {...}}

    Returns None if no question data is present or validation fails.
    """
    q_dict = parsed.get("question") or parsed.get("next_question")
    if not isinstance(q_dict, dict):
        return None
    q = TeachQuestion.from_dict(q_dict)
    if q.validate():
        return None
    return q


def parse_evaluation_from_json(parsed: dict) -> Optional[TeachEvaluation]:
    """Extract a TeachEvaluation from a parsed EVALUATE_ANSWER JSON response."""
    e_dict = parsed.get("evaluation")
    if not isinstance(e_dict, dict):
        return None
    return TeachEvaluation.from_dict(e_dict)


def validate_teach_response(parsed: dict, phase: str) -> list[str]:
    """Validate the top-level structure of a parsed teach JSON response.

    Returns a list of error messages (empty = valid).
    """
    errs: list[str] = []
    if not isinstance(parsed, dict):
        return ["Parsed JSON is not an object"]

    phase_val = parsed.get("phase")
    if phase_val != phase:
        errs.append(f"Expected phase={phase!r}, got {phase_val!r}")

    if phase == "FIRST_QUESTION":
        q = parsed.get("question")
        if not isinstance(q, dict):
            errs.append("Missing or invalid 'question' field")
        else:
            tq = TeachQuestion.from_dict(q)
            errs.extend(tq.validate())
    elif phase == "EVALUATE_ANSWER":
        e = parsed.get("evaluation")
        if not isinstance(e, dict):
            errs.append("Missing or invalid 'evaluation' field")
        nq = parsed.get("next_question")
        # next_question can be null (all done) or an object
        if nq is not None and not isinstance(nq, dict):
            errs.append("next_question must be null or a question object")

    return errs


# ═══════════════════════════════════════════════════════════════════════
# 试卷结构化提取 — OCR 后一次性提取全部题目+答案+解析
# ═══════════════════════════════════════════════════════════════════════

import hashlib as _hashlib
import time as _time

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExtractedExam:
    """整份试卷的结构化数据，OCR 后由 LLM 一次性提取。

    所有题目、答案、解析在逐题教学开始前就已准备好。
    平台用此数据验证 DT 输出的题号和答案，不依赖 DT 的 JSON。
    """
    questions: list[TeachQuestion]
    total: int
    raw_ocr: str
    raw_file_hash: str = ""
    _extracted_at: float = 0.0


# OCR 原文 → 试卷结构化的提取 prompt
_EXAM_EXTRACT_PROMPT = """你是一个专业的试卷结构化提取助手。

请从以下 OCR 文本中提取所有题目，严格按照 JSON 格式输出。
不要增加、删减或改写题目内容，原样保留题目正文。

要求：
1. 识别每道题的题号（index），从 1 开始连续编号
2. 识别题型（question_type）：choice / fill_blank / short_answer / written
3. 选择题需提取选项（options）和正确答案（answer_key）
4. 提取解题解析（explanation）
5. 识别知识点（knowledge_point），格式如"数学/三角形/全等三角形"
6. 如果某题的答案或解析不明确，answer_key 填 ""，explanation 填 "待补充"

输出格式（必须是最外层的 JSON 对象，不要用代码块包裹）：
{
  "total": 3,
  "questions": [
    {
      "index": 1,
      "content": "题目正文...",
      "question_type": "choice",
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "answer_key": "B",
      "explanation": "解题步骤...",
      "knowledge_point": "学科/章/节"
    }
  ]
}

OCR 文本：
"""


def extract_exam_from_ocr(ocr_text: str, llm_client=None) -> Optional[ExtractedExam]:
    """调用 LLM 从 OCR 文本中提取结构化试卷数据。

    只在 OCR 后调用一次。提取成功后可缓存（按 sha256）。
    """
    if not ocr_text or not ocr_text.strip():
        return None
    if llm_client is None:
        return None

    import json as _json

    try:
        raw = llm_client.complete(_EXAM_EXTRACT_PROMPT + ocr_text)
        if not raw or not raw.strip():
            return None
        extracted_json = extract_json_block(raw.strip())
        if extracted_json is None:
            return None
        parsed = _json.loads(extracted_json)
    except Exception:
        return None

    questions_raw = parsed.get("questions", []) if isinstance(parsed, dict) else []
    if not questions_raw:
        return None

    questions: list[TeachQuestion] = []
    for qr in questions_raw:
        if not isinstance(qr, dict):
            continue
        try:
            index = int(qr.get("index", 0))
            if index <= 0:
                continue
            questions.append(TeachQuestion(
                index=index,
                total=parsed.get("total", len(questions_raw)),
                question_type=qr.get("question_type", "short_answer"),
                content=str(qr.get("content", "")),
                answer_key=str(qr.get("answer_key", "")),
                explanation=str(qr.get("explanation", "")),
                knowledge_point=str(qr.get("knowledge_point", "")),
                options=qr.get("options") if isinstance(qr.get("options"), dict) else None,
            ))
        except (ValueError, TypeError):
            continue

    if not questions:
        return None

    file_hash = _hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()[:16]
    return ExtractedExam(
        questions=questions,
        total=len(questions),
        raw_ocr=ocr_text,
        raw_file_hash=file_hash,
        _extracted_at=_time.time(),
    )


def get_question_by_index(exam: ExtractedExam, index: int) -> Optional[TeachQuestion]:
    """从提取的试卷中按题号取题目（1-based）。"""
    for q in exam.questions:
        if q.index == index:
            return q
    return None


def validate_question_against_exam(
    dt_question: dict,
    exam: ExtractedExam,
    expected_idx: int,
) -> dict:
    """验证 DT 输出的题目数据，用预提取的试卷数据修正。

    Returns:
        {"valid": bool, "corrected": dict, "action": "pass"|"nudge"}
    """
    if not dt_question or not isinstance(dt_question, dict):
        return {"valid": False, "corrected": {}, "action": "nudge"}

    correct_q = get_question_by_index(exam, expected_idx)
    if not correct_q:
        return {"valid": False, "corrected": {}, "action": "nudge"}

    dt_idx = int(dt_question.get("index", 0))
    corrected = dict(dt_question)

    if dt_idx != expected_idx:
        # DT 题号错了 → 用预提取数据覆盖
        corrected["index"] = expected_idx
        corrected["content"] = correct_q.content
        corrected["question_type"] = correct_q.question_type
        corrected["answer_key"] = correct_q.answer_key
        corrected["explanation"] = correct_q.explanation
        corrected["knowledge_point"] = correct_q.knowledge_point
        if correct_q.options:
            corrected["options"] = correct_q.options
        return {"valid": True, "corrected": corrected, "action": "pass"}

    # 题号正确，只校正 answer_key（防止 DT 给错答案）
    if corrected.get("answer_key", "") != correct_q.answer_key:
        corrected["answer_key"] = correct_q.answer_key

    return {"valid": True, "corrected": corrected, "action": "pass"}


def validate_evaluation_against_exam(
    dt_evaluation: dict,
    exam: ExtractedExam,
    current_idx: int,
    student_answer: str,
) -> dict:
    """验证 DT 的评估，用预提取的试卷数据修正。

    DT 的 feedback/explanation 保留教学价值，
    但 is_correct/score 由平台用正确 key 决定。
    """
    correct_q = get_question_by_index(exam, current_idx)
    if not correct_q:
        # 没有预提取数据 → 信任 DT
        return {
            "is_correct": dt_evaluation.get("is_correct", False),
            "score": float(dt_evaluation.get("score", 0.0)),
            "correct_answer": dt_evaluation.get("answer_key", ""),
            "feedback": dt_evaluation.get("feedback", ""),
            "explanation": dt_evaluation.get("explanation", ""),
            "knowledge_point": dt_evaluation.get("knowledge_point", ""),
        }

    correct_key = correct_q.answer_key
    if not correct_key:
        # 没有标准答案 → 信任 DT
        return {
            "is_correct": dt_evaluation.get("is_correct", False),
            "score": float(dt_evaluation.get("score", 0.0)),
            "correct_answer": dt_evaluation.get("answer_key", ""),
            "feedback": dt_evaluation.get("feedback", ""),
            "explanation": dt_evaluation.get("explanation", ""),
            "knowledge_point": correct_q.knowledge_point,
        }

    # 平台判题（用预提取的正确 key）
    from tutor_platform.rag.extractors import _match_answers
    is_correct = _match_answers(student_answer, correct_key)
    score = 1.0 if is_correct else 0.0
    if not is_correct:
        try:
            from tutor_platform.rag.extractors import _match_answers_semantic
            if _match_answers_semantic(student_answer, correct_key):
                score = 0.5
        except Exception:
            pass

    return {
        "is_correct": is_correct,
        "score": score,
        "correct_answer": correct_key,
        "feedback": dt_evaluation.get("feedback", ""),
        "explanation": dt_evaluation.get("explanation", ""),
        "knowledge_point": correct_q.knowledge_point,
    }
