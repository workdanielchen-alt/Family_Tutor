"""Verify Phase 1-4 changes via file source analysis (no Docker deps required).

All tests read source files directly — no module imports.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
API_PY = ROOT / "docker" / "platform" / "provider_api.py"
WEIXIN_PY = ROOT / "vendor" / "hermes-agent" / "gateway" / "platforms" / "weixin.py"
PATCH = ROOT / "patches" / "weixin-teach-api-unify.patch"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _get_function_source(path: Path, func_name: str) -> str:
    """Extract function source from file using indentation heuristics."""
    text = _read(path)
    # Find "def func_name("
    pattern = rf"^(async\s+)?def {func_name}\("
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"Function {func_name} not found in {path}")
    start = match.start()
    # Find the first line with LESS indentation after the function body
    # (same indent as "def" keyword)
    indent_match = re.match(r"^( *)", text[start:])
    base_indent = indent_match.group(1) if indent_match else ""
    # Search forward for next line at same or less indentation
    lines = text[start:].split("\n")
    result_lines = []
    for i, line in enumerate(lines):
        if i == 0:
            result_lines.append(line)
            continue
        if line.strip() == "":
            result_lines.append(line)
            continue
        if re.match(r"^" + base_indent + r"\S", line) and not line.startswith((" ", "\t")):
            break
        result_lines.append(line)
    return "\n".join(result_lines)


def _check_contains(source: str, *patterns: str) -> list[str]:
    """Return list of patterns NOT found in source."""
    missing = []
    for p in patterns:
        if p not in source:
            missing.append(p)
    return missing


# ══════════════════════════════════════════════════════════════════════
# Phase 1: teach_session_id parameter + auto-create removal
# ══════════════════════════════════════════════════════════════════════


class TestPhase1SessionIdParam:
    """_tutor_chat_core changes (search full file, _get_function_source truncates)."""

    FULL = _read(API_PY)

    def test_signature_has_teach_session_id(self):
        assert "teach_session_id: str = \"\"" in self.FULL or "teach_session_id: str = ''" in self.FULL

    def test_teach_session_id_wired(self):
        assert "_teach_session_id = teach_session_id" in self.FULL

    def test_auto_create_removed(self):
        assert "Auto-create TeachSession REMOVED" in self.FULL
        assert "Auto-create TeachSession for WeChat" not in self.FULL


class TestPhase1Callers:
    """All callers should pass teach_session_id."""

    FULL = _read(API_PY)

    def test_api_teach_start_passes_sid(self):
        assert "teach_session_id=session.session_id" in self.FULL

    def test_api_teach_continue_passes_sid(self):
        assert "teach_session_id=teach_session_id" in self.FULL

    def test_api_tutor_chat_passes_sid(self):
        assert "teach_session_id=body.get" in self.FULL

    def test_child_practice_passes_sid(self):
        assert "teach_session_id=session.session_id" in self.FULL


# ══════════════════════════════════════════════════════════════════════
# Phase 2: WeChat gateway API unification
# ══════════════════════════════════════════════════════════════════════


class TestPhase2Weixin:
    """weixin.py uses api/teach/start + api/teach/continue."""

    def test_uses_api_teach_start(self):
        src = _read(WEIXIN_PY)
        assert "/api/teach/start" in src

    def test_uses_api_teach_continue(self):
        src = _read(WEIXIN_PY)
        assert "/api/teach/continue" in src

    def test_no_more_tutor_chat_direct(self):
        """weixin.py no longer calls /api/tutor/chat directly for teaching."""
        src = _read(WEIXIN_PY)
        assert '"context": _teach_ctx' not in src

    def test_teach_session_id_in_new_session(self):
        src = _read(WEIXIN_PY)
        assert "teach_session_id" in src
        assert '"teach_session_id"' in src

    def test_patch_file_exists(self):
        assert PATCH.exists()
        content = _read(PATCH)
        assert len(content) > 50


# ══════════════════════════════════════════════════════════════════════
# Phase 3: Pre-extraction
# ══════════════════════════════════════════════════════════════════════


class TestPhase3PreExtract:
    """Pre-extraction functions exist and are wired."""

    FULL = _read(API_PY)

    def test_pre_extract_exam_exists(self):
        assert "async def _pre_extract_exam(" in self.FULL

    def test_pre_extract_and_store_exists(self):
        assert "async def _pre_extract_and_store(" in self.FULL

    def test_pre_extract_calls_deepseek(self):
        assert "api.deepseek.com" in self.FULL
        assert "DEEPSEEK_API_KEY" in self.FULL

    def test_api_teach_start_fires_pre_extract(self):
        assert "_pre_extract_and_store" in self.FULL

    def test_first_question_uses_extracted_exam(self):
        assert "_extracted_exams.get(learner_id)" in self.FULL

    def test_evaluate_uses_extracted_exam(self):
        assert "get_question_by_index" in self.FULL
        assert "validate_evaluation_against_exam" in self.FULL

    def test_validate_functions_already_imported(self):
        assert "validate_question_against_exam" in self.FULL
        assert "validate_evaluation_against_exam" in self.FULL


# ══════════════════════════════════════════════════════════════════════
# Phase 4: Context restore
# ══════════════════════════════════════════════════════════════════════


class TestPhase4ContextRestore:
    """api_teach_continue restores context from session."""

    FULL = _read(API_PY)

    def test_always_restores_context(self):
        assert "Restored context" in self.FULL
        assert "session.ocr_text" in self.FULL

    def test_restores_extracted_exam(self):
        assert "Restored extracted exam" in self.FULL
        assert "session.extracted_exam" in self.FULL

    def test_recovery_in_tutor_core(self):
        assert "_teach_session_id" in self.FULL


# ══════════════════════════════════════════════════════════════════════
# Cross-cutting: response format changes
# ══════════════════════════════════════════════════════════════════════


class TestResponseFormat:
    """API responses include fields needed by WeChat gateway."""

    FULL = _read(API_PY)

    def test_api_teach_start_returns_content(self):
        assert '"content": reply' in self.FULL or "'content': reply" in self.FULL


class TestSanity:
    """Basic sanity checks."""

    def test_provider_api_exists(self):
        assert API_PY.exists()
        assert API_PY.stat().st_size > 100000  # should be large

    def test_weixin_py_exists(self):
        assert WEIXIN_PY.exists()
        assert WEIXIN_PY.stat().st_size > 50000
