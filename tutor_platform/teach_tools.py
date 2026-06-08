# teach_tools.py — 教学工具集：RAG 查询 + 课程上下文
#
# 为 Agentic Loop 提供可调用的工具，让教学不再局限于试卷文本，
# 可以查询知识点库、教材向量库等获取补充资料。
#
# 工具集合:
# - rag_lookup(kp_id, subject, question_type): 查询向量库中的相关教材内容
# - get_curriculum_kp_info(kp_id, subject): 获取知识点在课程体系中的上下文
# - get_review_context(learner_id): 获取待复习知识点
# - get_weak_points_context(learner_id): 获取薄弱知识点

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── RAG 查询工具 ──────────────────────────────────────────────────


async def rag_lookup(
    kp_id: str,
    subject: str = "math",
    query_text: str = "",
) -> str:
    """查询 ChromaDB 向量库中与知识点相关的教材内容。

    Args:
        kp_id: 知识点ID，如 "math/grade7/semester1/ch1/kp1"
        subject: 学科
        query_text: 额外查询文本（与当前题目相关）

    Returns:
        格式化的教材引用文本，或空字符串（无匹配时）
    """
    if not kp_id:
        return ""

    try:
        from tutor_platform.unified_provider import get_provider_instance

        provider = get_provider_instance()

        # 构建查询文本：知识点名称 + 题目上下文
        kp_name = kp_id.split("/")[-1] if "/" in kp_id else kp_id
        search_query = f"{kp_name} {query_text}".strip()

        # 查询教材向量库 (kb 名称基于学科)
        kb_name = _subject_to_kb(subject)
        results = await provider.query(
            collection_name=kb_name,
            query_texts=[search_query],
            n_results=3,
        )

        if not results:
            return ""

        # 格式化为可注入 LLM 的文本
        lines = [f"## 📚 教材相关 ({kp_id})"]
        for i, doc in enumerate(results[:3], 1):
            text = doc.get("content", "") or doc.get("document", "") or ""
            meta = doc.get("metadata", {}) or {}
            source = meta.get("source", "") or meta.get("filename", "")
            if text.strip():
                source_tag = f" (来源: {source})" if source else ""
                lines.append(f"**引用{i}**{source_tag}:\n{text.strip()[:500]}")
        return "\n\n".join(lines)

    except Exception as e:
        logger.debug("rag_lookup failed (non-fatal): %s", e)
        return ""


def _subject_to_kb(subject: str) -> str:
    """学科名 → ChromaDB knowledge base 名称."""
    kb_map = {
        "math": "math_textbook",
        "physics": "physics_textbook",
        "chemistry": "chemistry_textbook",
        "english": "english_textbook",
    }
    return kb_map.get(subject, f"{subject}_textbook")


# ── 课程体系工具 ──────────────────────────────────────────────────


def get_curriculum_kp_info(
    kp_id: str,
    subject: str = "math",
) -> str:
    """获取知识点在课程体系中的完整上下文。

    Returns:
        格式化的文本，包含章节位置、前后知识点、考试重要性等。
    """
    if not kp_id:
        return ""

    try:
        from domains.curriculum import load, get_kp_by_id

        data = load(subject=subject)
        if not data:
            return ""

        kp = get_kp_by_id(kp_id, subject=subject)
        if not kp:
            return ""

        lines = [
            f"## 📖 课程体系 ({kp_id})",
            f"- **知识点**: {kp.get('name', '未知')}",
            f"- **重要性**: {kp.get('importance', '未知')}",
            f"- **前置知识**: {', '.join(kp.get('prerequisites', [])) or '无'}",
            f"- **后续关联**: {', '.join(kp.get('related', [])) or '无'}",
        ]

        desc = kp.get("description", "")
        if desc:
            lines.append(f"- **描述**: {desc}")

        return "\n".join(lines)

    except Exception as e:
        logger.debug("get_curriculum_kp_info failed (non-fatal): %s", e)
        return ""


# ── 复习/薄弱点工具 (异步) ─────────────────────────────────────────


async def get_review_context(learner_id: str) -> str:
    """获取学习者到期复习的知识点上下文。

    Returns:
        格式化的待复习知识点文本，可供注入 system prompt。
    """
    try:
        from domains.tutoring.mastery import get_due_reviews

        due = await asyncio.to_thread(get_due_reviews, learner_id)
        if not due:
            return ""

        lines = ["## 📋 到期复习知识点（优先复习）"]
        for r in due[:3]:
            name = r["kp_id"].split("/")[-1]
            pct = int(r["level"] * 100)
            lines.append(f"- {name}（掌握度 {pct}%，上次复习 {r.get('due_date', '未知')}）")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("get_review_context failed: %s", e)
        return ""


async def get_weak_points_context(learner_id: str) -> str:
    """获取学习者的薄弱知识点上下文。

    Returns:
        格式化的薄弱知识点文本。
    """
    try:
        from domains.tutoring.mastery import weak_points

        weak = await asyncio.to_thread(weak_points, learner_id)
        if not weak:
            return ""

        lines = ["## ⚠️ 薄弱知识点（教学重点）"]
        for w in weak[:3]:
            name = w["kp_id"].split("/")[-1]
            pct = int(w["level"] * 100)
            lines.append(f"- {name}（正确率 {pct}%，已答 {w.get('total', 0)} 题）")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("get_weak_points_context failed: %s", e)
        return ""


async def get_kp_mastery_context(
    learner_id: str,
    kp_id: str,
) -> str:
    """获取指定知识点的掌握度信息。

    Args:
        learner_id: 学习者 ID
        kp_id: 知识点 ID，如 "数学/分式/分式有意义的条件"

    Returns:
        格式化的掌握度文本，可用于注入 LLM context。
        如果无记录则返回空字符串。
    """
    if not kp_id or not learner_id:
        return ""

    try:
        from domains.tutoring.mastery import get_mastery

        data = await asyncio.to_thread(get_mastery, learner_id, kp_id)
        if not data or not isinstance(data, dict):
            return ""

        level = data.get("level", 0.0)
        total = data.get("total", 0)
        correct = data.get("correct", 0)
        kp_name = kp_id.split("/")[-1]
        pct = int(level * 100)

        # 根据掌握度生成教学建议
        guidance = ""
        if level < 0.3 and total >= 2:
            guidance = "（该生在此知识点上较为薄弱，建议重点讲解基础概念）"
        elif level < 0.5:
            guidance = "（该生需要巩固，建议加强练习）"
        elif level >= 0.8 and total >= 3:
            guidance = "（该生掌握较好，可以减少提示直接出题）"

        lines = [
            f"## 📊 知识点掌握度 ({kp_name})",
            f"- **掌握度**: {pct}%（已答 {total} 题，正确 {correct} 题）",
        ]
        if guidance:
            lines.append(f"- **教学建议**: {guidance}")

        return "\n".join(lines)

    except Exception as e:
        logger.debug("get_kp_mastery_context failed: %s", e)
        return ""


# ── 可视化工具 ───────────────────────────────────────────────


GGB_SCRIPT_TEMPLATES: dict[str, str] = {
    "quadratic_function": """### 二次函数 y = ax² + bx + c
a = Slider(-3, 3, 0.1, 1, 200, False, True, False, False)
b = Slider(-5, 5, 0.1, 0, 200, False, True, False, False)
c = Slider(-5, 5, 0.1, 0, 200, False, True, False, False)
f(x) = a*x^2 + b*x + c
vertex = ( -b/(2a), f(-b/(2a)) )
axis: x = -b/(2a)
# 标注关键点
Root(f)
Intersect(f, xAxis)
""",
    "linear_function": """### 一次函数 y = kx + b
k = Slider(-3, 3, 0.1, 1, 200, False, True, False, False)
b = Slider(-5, 5, 0.1, 0, 200, False, True, False, False)
f(x) = k*x + b
Intersect(f, xAxis)
Intersect(f, yAxis)
""",
    "inverse_function": """### 反比例函数 y = k/x
k = Slider(-5, 5, 0.1, 1, 200, False, True, False, False)
f(x) = k / x
""",
    "triangle": """### 三角形
A = (0, 0)
B = (4, 0)
C = (1, 3)
Polygon(A, B, C)
Angle(A, B, C)
Angle(B, C, A)
Angle(C, A, B)
""",
    "circle": """### 圆
C = (0, 0)
r = Slider(1, 5, 0.1, 2, 200, False, True, False, False)
circle: (x - x(C))^2 + (y - y(C))^2 = r^2
""",
    "pythagorean": """### 勾股定理
A = (0, 0)
B = (3, 0)
C = (0, 4)
Polygon(A, B, C)
c = Segment(B, C)
a = Segment(A, B)
b = Segment(A, C)
Text(0.5, -0.5, "a = " + a)
Text(3.2, 2, "b = " + b)
Text(1.5, 2.2, "c = " + c)
""",
}


async def generate_geogebra_script(
    kp_id: str = "",
    query_text: str = "",
) -> str:
    """根据知识点 ID 生成 GeoGebra 脚本 (ggbscript)。

    LLM 可将返回的脚本直接嵌入教学回复，前端自动渲染为交互图形。

    Returns:
        可直接嵌入 Markdown 的 ggbscript 代码块，或空字符串（无匹配模板时）。
    """
    if not kp_id and not query_text:
        return ""

    # 匹配知识点 → GeoGebra 模板
    kp_lower = (kp_id + " " + query_text).lower()
    template_key = "quadratic_function"  # default
    if any(kw in kp_lower for kw in ("一次函数", "线性", "linear", "正比例")):
        template_key = "linear_function"
    elif any(kw in kp_lower for kw in ("反比例", "inverse", "反函数")):
        template_key = "inverse_function"
    elif any(kw in kp_lower for kw in ("三角形", "三角", "triangle", "全等", "相似")):
        template_key = "triangle"
    elif any(kw in kp_lower for kw in ("圆", "circle", "圆周", "圆心")):
        template_key = "circle"
    elif any(kw in kp_lower for kw in ("勾股", "pythagorean", "毕达哥拉斯")):
        template_key = "pythagorean"

    script = GGB_SCRIPT_TEMPLATES.get(template_key, GGB_SCRIPT_TEMPLATES["quadratic_function"])
    return f"```ggbscript\n{script.strip()}\n```"


async def generate_function_plot(
    formula: str = "",
    x_range: str = "",
) -> str:
    """生成函数绘图代码块（前端 ``funcplot`` 渲染器使用）。

    Args:
        formula: 函数表达式，如 "x^2 - 3x + 2"、"2x + 1"
        x_range: x 轴范围，如 "-5:5"

    Returns:
        ``funcplot`` 代码块字符串，前端自动渲染为 SVG 图表。
    """
    if not formula:
        return ""

    # 清理输入
    formula = formula.strip().strip("$`")
    if formula.startswith("y=") or formula.startswith("f(x)="):
        formula = formula.split("=", 1)[1].strip()
    if not x_range:
        x_range = "-5:5"

    return f"```funcplot\n{formula}\n{x_range}\n```"


_NUMBERLINE_TPL = """```numberline
range: {x_min}:{x_max}
{points_line}{open_line}{highlight_line}```"""


async def generate_numberline(
    kp_id: str = "",
    query_text: str = "",
) -> str:
    """生成交互数轴代码块（``numberline``）。

    根据知识点 ID 自动选择合适的数轴配置（有理数标点、不等式解集、区间等）。

    Returns:
        ``numberline`` 代码块字符串，前端自动渲染为 SVG 数轴。
    """
    if not kp_id and not query_text:
        return ""

    kp_lower = (kp_id + " " + query_text).lower()

    # 不等式解集
    if any(kw in kp_lower for kw in ("不等式", "解集", "区间", "取值范围")):
        return _NUMBERLINE_TPL.format(
            x_min="-5", x_max="5",
            points_line="",
            open_line="open: 2\nhighlight: 2:5\n",
            highlight_line="",
        )

    # 有理数标点
    if any(kw in kp_lower for kw in ("有理数", "正数", "负数", "相反数", "绝对值", "整数")):
        return _NUMBERLINE_TPL.format(
            x_min="-5", x_max="5",
            points_line="points: -3,-1,0,2,4\n",
            open_line="",
            highlight_line="",
        )

    # 实数
    if any(kw in kp_lower for kw in ("实数", "无理数", "平方根", "立方根")):
        return _NUMBERLINE_TPL.format(
            x_min="-3", x_max="5",
            points_line="points: -1.414,0,1.732,3.14\n",
            open_line="",
            highlight_line="highlight: 2:3\n",
        )

    # 默认：空数轴
    return _NUMBERLINE_TPL.format(
        x_min="-5", x_max="5",
        points_line="",
        open_line="",
        highlight_line="",
    )


# ── 工具执行器 (Agentic Loop 用) ──────────────────────────────────


async def execute_teach_tool(
    tool_name: str,
    learner_id: str = "",
    kp_id: str = "",
    subject: str = "math",
    query_text: str = "",
    question_content: str = "",
) -> str:
    """Agentic Loop 的统一工具执行入口。

    Args:
        tool_name: 工具名 (rag_lookup, get_curriculum_kp_info, get_review_context, get_weak_points_context)
        learner_id: 学习者ID
        kp_id: 知识点ID
        subject: 学科
        query_text: 补充查询文本
        question_content: 当前题目内容（用于RAG查询）

    Returns:
        工具执行结果文本
    """
    tool_map = {
        "rag_lookup": lambda: rag_lookup(
            kp_id=kp_id,
            subject=subject,
            query_text=query_text or question_content,
        ),
        "get_curriculum_kp_info": lambda: get_curriculum_kp_info(
            kp_id=kp_id,
            subject=subject,
        ),
        "get_review_context": lambda: get_review_context(learner_id),
        "get_weak_points_context": lambda: get_weak_points_context(learner_id),
    }
    # ── 可视化工具 (GeoGebra / 函数绘图) ──
    if tool_name == "geogebra":
        return await generate_geogebra_script(
            kp_id=kp_id,
            query_text=query_text or question_content,
        )
    if tool_name == "funcplot":
        return await generate_function_plot(
            formula=query_text or question_content,
            x_range=kp_id,  # reuse kp_id as x_range param, e.g. "-5:5"
        )
    if tool_name == "numberline":
        return await generate_numberline(
            kp_id=kp_id,
            query_text=query_text or question_content,
        )


    handler = tool_map.get(tool_name)
    if not handler:
        logger.warning("Unknown tool: %s", tool_name)
        return ""

    try:
        result = handler()
        if asyncio.iscoroutine(result):
            result = await result
        return str(result) if result else ""
    except Exception as e:
        logger.warning("Tool %s failed: %s", tool_name, e)
        return ""
