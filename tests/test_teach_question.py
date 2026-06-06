"""Unit tests for tutor_platform.teach_question — JSON parsing & validation."""

import pytest
from tutor_platform.teach_question import (
    TeachQuestion,
    TeachEvaluation,
    extract_json_block,
    parse_teach_response,
    parse_question_from_json,
    parse_evaluation_from_json,
    validate_teach_response,
)


# ── extract_json_block ────────────────────────────────────────────────────


def test_extract_fenced_json():
    text = 'Some text\n```json\n{"a": 1}\n```\nMore text'
    assert extract_json_block(text) == '{"a": 1}'


def test_extract_last_fenced():
    text = '```json\n{"first": 1}\n```\n```json\n{"last": 2}\n```'
    assert extract_json_block(text) == '{"last": 2}'


def test_extract_bare_json():
    text = '{"phase": "FIRST_QUESTION"}'
    assert extract_json_block(text) == '{"phase": "FIRST_QUESTION"}'


def test_extract_no_json():
    assert extract_json_block("Just plain text") is None


def test_extract_json_without_lang_label():
    text = '```\n{"a": 1}\n```'
    assert extract_json_block(text) == '{"a": 1}'


# ── parse_teach_response ───────────────────────────────────────────────────


def test_parse_valid_first_question():
    text = '''```json
{
  "phase": "FIRST_QUESTION",
  "question": {
    "index": 1,
    "total": 12,
    "question_type": "choice",
    "content": "What is 2+2?",
    "options": {"A": "3", "B": "4"},
    "answer_key": "B",
    "explanation": "2+2=4",
    "knowledge_point": "math/arithmetic",
    "hints": ["L1", "L2", "L3"],
    "difficulty": "easy"
  }
}
```'''
    parsed = parse_teach_response(text)
    assert parsed is not None
    assert parsed["phase"] == "FIRST_QUESTION"
    q = parse_question_from_json(parsed)
    assert q is not None
    assert q.index == 1
    assert q.total == 12
    assert q.question_type == "choice"
    assert q.answer_key == "B"
    assert q.options == {"A": "3", "B": "4"}
    assert len(q.hints) == 3
    assert q.validate() == []


def test_parse_valid_eval_answer():
    text = '''```json
{
  "phase": "EVALUATE_ANSWER",
  "evaluation": {
    "is_correct": true,
    "score": 1.0,
    "feedback": "Great!",
    "answer_key": "B",
    "explanation": "Well done"
  },
  "next_question": {
    "index": 2,
    "total": 12,
    "question_type": "fill_blank",
    "content": "Fill this: ___",
    "answer_key": "test",
    "explanation": "Because...",
    "hints": ["Hint"],
    "difficulty": "medium"
  }
}
```'''
    parsed = parse_teach_response(text)
    assert parsed is not None
    e = parse_evaluation_from_json(parsed)
    assert e is not None
    assert e.is_correct is True
    assert e.score == 1.0
    assert e.feedback == "Great!"
    nq = parse_question_from_json(parsed)
    assert nq is not None
    assert nq.index == 2


def test_parse_done_null_next():
    text = '{"phase": "EVALUATE_ANSWER", "evaluation": {"is_correct": true, "score": 1.0, "feedback": "Done!", "answer_key": "C", "explanation": ""}, "next_question": null}'
    parsed = parse_teach_response(text)
    assert parsed is not None
    assert parsed["next_question"] is None
    nq = parse_question_from_json(parsed)
    assert nq is None  # null → None


def test_parse_invalid_json():
    assert parse_teach_response("not json at all") is None
    assert parse_teach_response("```json\n{broken\n```") is None


# ── parse_question_from_json edge cases ────────────────────────────────────


def test_question_missing_options_for_choice():
    """Choice questions without options fail validation → parsed as None."""
    q = parse_question_from_json({
        "question": {
            "index": 1, "total": 5,
            "question_type": "choice",
            "content": "Q?",
            "answer_key": "A",
            "explanation": "E",
        }
    })
    assert q is None  # strict: choice requires options


def test_question_minimal_valid():
    q = parse_question_from_json({
        "question": {
            "index": 1, "total": 5,
            "question_type": "short_answer",
            "content": "Explain...",
            "answer_key": "42",
            "explanation": "Because...",
        }
    })
    assert q is not None
    assert q.validate() == []


# ── validate_teach_response ────────────────────────────────────────────────


def test_validate_first_question_phase_mismatch():
    parsed = {
        "phase": "EVALUATE_ANSWER",
        "question": {"index": 1, "total": 5, "question_type": "choice",
                     "content": "Q", "answer_key": "A", "explanation": "E",
                     "options": {"A": "x"}},
    }
    errs = validate_teach_response(parsed, "FIRST_QUESTION")
    assert len(errs) >= 1
    assert any("phase" in e.lower() for e in errs)


def test_validate_eval_missing_evaluation():
    parsed = {"phase": "EVALUATE_ANSWER"}
    errs = validate_teach_response(parsed, "EVALUATE_ANSWER")
    assert len(errs) >= 1


def test_validate_eval_null_next_ok():
    parsed = {
        "phase": "EVALUATE_ANSWER",
        "evaluation": {"is_correct": True, "score": 1.0, "feedback": "ok",
                       "answer_key": "B", "explanation": "e"},
        "next_question": None,
    }
    errs = validate_teach_response(parsed, "EVALUATE_ANSWER")
    assert errs == []


# ── TeachEvaluation ────────────────────────────────────────────────────────


def test_evaluation_from_dict():
    e = TeachEvaluation.from_dict({
        "is_correct": False,
        "score": 0.5,
        "feedback": "Almost!",
        "answer_key": "B",
        "explanation": "Try again",
    })
    assert e.is_correct is False
    assert e.score == 0.5
    d = e.to_dict()
    assert d["is_correct"] is False
    assert d["score"] == 0.5


# ── TeachQuestion integer defaults ─────────────────────────────────────────


def test_question_coerces_string_index():
    q = TeachQuestion.from_dict({
        "index": "3",
        "total": "10",
        "question_type": "choice",
        "content": "Q",
        "answer_key": "A",
        "explanation": "E",
        "options": {"A": "a"},
    })
    assert q.index == 3
    assert q.total == 10
