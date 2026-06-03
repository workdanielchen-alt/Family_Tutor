"""Phase 3: Semantic structuring — assemble layout blocks into exam questions.

Takes the output of Phase 1 (PageLayout) and Phase 2 (BlockContent list per page),
then applies rule-based heuristics to:

1. Detect question boundaries (题号模式 + spacing)
2. Classify question types (choice / fill-blank / solution)
3. Pair figures with their parent questions (bbox proximity)
4. Extract paper metadata from header blocks

No LLM calls in this phase — pure Python rules.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from tutor_platform.rag.block_ocr import BlockContent
from tutor_platform.rag.layout_engine import LayoutBlock, PageLayout


# ── Data types ───────────────────────────────────────────────────

QuestionType = Literal["choice", "fill_blank", "solution", "construction", "unknown"]


@dataclass
class QuestionFigure:
    """A figure attached to a question."""

    figure_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    page_num: int = 0
    block_id: int = 0
    image_bytes: bytes | None = None
    description: dict | None = None
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)


@dataclass
class Question:
    """A single exam question."""

    question_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    index: int = 0                       # 1-based question number
    type: QuestionType = "unknown"
    content: str = ""                    # Markdown (with LaTeX)
    options: list[str] = field(default_factory=list)  # A./B./C./D.
    answer: str | None = None            # Extracted answer if present
    figures: list[QuestionFigure] = field(default_factory=list)
    page_num: int = 0
    score: float | None = None           # e.g. "(5分)" parsed


@dataclass
class PaperMetadata:
    """Structured paper metadata."""

    subject: str | None = None
    grade: str | None = None
    exam_type: str | None = None   # 期中/期末/月考/模拟
    year: int | None = None
    total_score: float | None = None
    duration_minutes: int | None = None
    raw_header: str | None = None  # original OCR text of header


@dataclass
class ExamPaper:
    """Complete structured exam paper."""

    paper_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    questions: list[Question] = field(default_factory=list)
    total_pages: int = 0
    raw_file_hash: str = ""


# ── Regex patterns ───────────────────────────────────────────────

# Question number patterns: "1.", "1．", "(1)", "1、", "一、"
_RE_QUESTION_START = re.compile(
    r"^\s*(?:\d{1,3}[．.、]\s|[（(]\s*\d{1,3}\s*[）)]|[一二三四五六七八九十]{1,2}[、．.]\s)"
)

# Choice option patterns: "A.", "A．", "(A)", "A、" etc.
_RE_CHOICE_OPTION = re.compile(
    r"^\s*[A-Da-d][．.、]\s|^\s*[（(]\s*[A-Da-d]\s*[）)]"
)

# Fill-blank indicators
_RE_BLANK = re.compile(r"_{2,}|…{2,}")

# Score extraction: "(5分)", "(10 分)"
_RE_SCORE = re.compile(r"[（(]\s*(\d+)\s*分\s*[）)]")

# Metadata keywords
_SUBJECT_MAP = {
    "数学": "math", "物理": "physics", "化学": "chemistry",
    "语文": "chinese", "英语": "english", "生物": "biology",
}
_GRADE_PATTERN = re.compile(r"(七|八|九|高一|高二|高三|初[一二三]|高[一二三])\s*(?:年级|年)?")
_EXAM_TYPE_MAP = {
    "期中": "midterm", "期末考试": "final", "期末": "final",
    "月考": "monthly", "模拟": "mock", "中考": "zhongkao",
    "高考": "gaokao", "一模": "mock1", "二模": "mock2",
}
_YEAR_PATTERN = re.compile(r"(20\d{2})")
_TIME_PATTERN = re.compile(r"(\d+)\s*分钟")
_TOTAL_SCORE_PATTERN = re.compile(r"(?:满分|总分)[：:]\s*(\d+)")


# ── Structurer ───────────────────────────────────────────────────

class ExamStructurer:
    """Assembles PageLayout + BlockContent[] → ExamPaper."""

    # Vertical gap (in points) that signals a new question vs same question content.
    QUESTION_GAP_THRESHOLD: float = 12.0

    # Maximum y-distance between a figure and its predecessor text block
    # for them to be paired.
    FIGURE_ATTACH_DISTANCE: float = 30.0

    @classmethod
    def structure(
        cls,
        pages: list[PageLayout],
        page_contents: list[list[BlockContent]],
        file_hash: str = "",
    ) -> ExamPaper:
        """Build an ExamPaper from layout + OCR results.

        Args:
            pages: Layout analysis from Phase 1.
            page_contents: BlockContent lists from Phase 2, one per page.
            file_hash: SHA-256 of original PDF for traceability.
        """
        paper = ExamPaper(raw_file_hash=file_hash, total_pages=len(pages))

        # Step 1: Extract metadata from first page header blocks
        paper.metadata = cls._extract_metadata(pages, page_contents)

        # Step 2: Build flat list of (block, content) with page context
        all_items: list[tuple[LayoutBlock, BlockContent, int]] = []
        for pg_idx, (layout, contents) in enumerate(zip(pages, page_contents)):
            for block, content in zip(layout.blocks, contents):
                all_items.append((block, content, pg_idx))

        # Step 3: Group into questions
        paper.questions = cls._group_into_questions(all_items)

        return paper

    # ── Metadata extraction ─────────────────────────────────────

    @classmethod
    def _extract_metadata(
        cls,
        pages: list[PageLayout],
        page_contents: list[list[BlockContent]],
    ) -> PaperMetadata:
        """Extract paper metadata from first page top blocks."""
        meta = PaperMetadata()

        if not pages or not page_contents:
            return meta

        # Scan first page top 20% height for header blocks
        page = pages[0]
        contents = page_contents[0]
        header_height = page.height * 0.20

        header_texts: list[str] = []
        for block, content in zip(page.blocks, contents):
            if block.bbox[3] > header_height:  # y1 > 20%
                break
            if content.ok and content.text:
                header_texts.append(content.text)

        combined = "\n".join(header_texts)
        meta.raw_header = combined if combined else None

        if not combined:
            return meta

        # Subject
        for cn_name, en_name in _SUBJECT_MAP.items():
            if cn_name in combined:
                meta.subject = en_name
                break

        # Grade
        gm = _GRADE_PATTERN.search(combined)
        if gm:
            grade_text = gm.group(0)
            meta.grade = grade_text

        # Exam type
        for cn_type, en_type in _EXAM_TYPE_MAP.items():
            if cn_type in combined:
                meta.exam_type = en_type
                break

        # Year
        ym = _YEAR_PATTERN.search(combined)
        if ym:
            try:
                meta.year = int(ym.group(1))
            except ValueError:
                pass

        # Total score
        sm = _TOTAL_SCORE_PATTERN.search(combined)
        if sm:
            try:
                meta.total_score = float(sm.group(1))
            except ValueError:
                pass

        # Duration
        tm = _TIME_PATTERN.search(combined)
        if tm:
            try:
                meta.duration_minutes = int(tm.group(1))
            except ValueError:
                pass

        return meta

    # ── Question grouping ───────────────────────────────────────

    @classmethod
    def _group_into_questions(
        cls,
        items: list[tuple[LayoutBlock, BlockContent, int]],
    ) -> list[Question]:
        """Group blocks into questions by detecting question-start patterns."""
        questions: list[Question] = []
        current_blocks: list[tuple[LayoutBlock, BlockContent, int]] = []
        current_index = 0

        def flush_question() -> None:
            nonlocal current_index
            if not current_blocks:
                return
            current_index += 1
            q = cls._build_question(current_index, current_blocks)
            questions.append(q)
            current_blocks.clear()

        for block, content, pg in items:
            text = content.text or ""
            is_question_start = bool(_RE_QUESTION_START.match(text)) if text else False

            if is_question_start and current_blocks:
                flush_question()

            current_blocks.append((block, content, pg))

        flush_question()  # last question
        return questions

    @classmethod
    def _build_question(
        cls,
        index: int,
        blocks: list[tuple[LayoutBlock, BlockContent, int]],
    ) -> Question:
        """Build a Question from its constituent blocks."""
        q = Question(index=index)
        text_parts: list[str] = []
        figure_blocks: list[tuple[LayoutBlock, BlockContent, int]] = []
        option_lines: list[str] = []

        for block, content, pg in blocks:
            q.page_num = pg  # last page wins (question may span pages)
            if content.type == "text":
                raw = content.text or ""
                # Detect choice options
                for line in raw.split("\n"):
                    line_s = line.strip()
                    if _RE_CHOICE_OPTION.match(line_s):
                        option_lines.append(line_s)
                    else:
                        text_parts.append(line_s)
            elif content.type == "image":
                figure_blocks.append((block, content, pg))

            # Extract score
            sm = _RE_SCORE.search(raw if content.type == "text" else "")
            if sm and q.score is None:
                try:
                    q.score = float(sm.group(1))
                except ValueError:
                    pass

        # Detect question type
        combined_text = "\n".join(text_parts)
        q.content = combined_text

        if option_lines:
            q.type = "choice"
            q.options = option_lines
        elif _RE_BLANK.search(combined_text):
            q.type = "fill_blank"
        elif combined_text.strip().startswith(("解:", "证明:", "解：", "证明：")):
            q.type = "solution"
        elif figure_blocks and not text_parts:
            q.type = "construction"
        else:
            q.type = "solution" if len(combined_text) > 80 else "unknown"

        # Attach figures
        for block, content, pg in figure_blocks:
            q.figures.append(
                QuestionFigure(
                    page_num=pg,
                    block_id=content.block_id,
                    image_bytes=content.image_bytes,
                    description=content.description,
                    bbox=block.bbox,
                )
            )

        return q
