"""
curriculum.py — 课程知识点体系加载器

从 config/domains-{subject}.yaml 加载学科知识点体系，供 AI 教学引用。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Subject-specific config file resolution:
# 1. DOMAINS_CONFIG env var → use it directly (full override)
# 2. subject="math"  → config/domains-math.yaml
# 3. subject="chemistry" → config/domains-chemistry.yaml
_DEFAULT_SUBJECT = "math"
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _resolve_path(subject: str | None = None) -> str:
    """Resolve config file path for the given subject."""
    env_path = os.getenv("DOMAINS_CONFIG")
    if env_path:
        return env_path

    subject = subject or os.getenv("DOMAINS_SUBJECT") or _DEFAULT_SUBJECT
    candidates = [
        _CONFIG_DIR / f"domains-{subject}.yaml",
        _CONFIG_DIR / f"domains-{subject}.yml",
        Path("/app/config") / f"domains-{subject}.yaml",   # Docker container
        Path("/config") / f"domains-{subject}.yaml",
    ]
    for fp in candidates:
        if fp.is_file():
            return str(fp)
    # Fallback: try old single-file paths
    for old in [_CONFIG_DIR / "domains.yaml", Path("/app/config/domains.yaml")]:
        if old.is_file():
            return str(old)
    return str(candidates[0])


_cache: dict[str, Any] | None = None
_cache_subject: str | None = None


def load(subject: str | None = None) -> dict[str, Any] | None:
    """Load a subject's knowledge point system.  Results are cached.

    Args:
        subject: Subject key like "math", "chemistry". Defaults to env
                 DOMAINS_SUBJECT or "math".

    Returns:
        Dict with domain, title, grades, exam_topics, etc.
    """
    global _cache, _cache_subject

    subject = subject or os.getenv("DOMAINS_SUBJECT") or _DEFAULT_SUBJECT

    if _cache is not None and _cache_subject == subject:
        return _cache

    path = _resolve_path(subject)
    if not os.path.isfile(path):
        logger.warning("Config not found for subject '%s' at %s", subject, path)
        return None
    if yaml is None:
        logger.warning("PyYAML not installed, can't load curriculum")
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        _cache = data
        _cache_subject = subject
        grades = data.get("grades", [])
        sem_count = sum(len(g.get("semesters", [])) for g in grades)
        logger.info("Curriculum loaded: %s (%d grades, %d semesters)",
                    data.get("title", subject), len(grades), sem_count)
        return data
    except Exception as e:
        logger.warning("Failed to load curriculum for '%s' from %s: %s",
                       subject, path, e)
        return None


def reload(subject: str | None = None) -> dict[str, Any] | None:
    """Force reload, bypassing cache."""
    global _cache, _cache_subject
    _cache = None
    _cache_subject = None
    return load(subject)


# ─────────────────────────────────────────────────────────────────────────────
# KP ID construction
# ─────────────────────────────────────────────────────────────────────────────

def get_kp_id(domain: str, grade: str, semester: str, chapter: str, kp: str) -> str:
    """Build a standard kp_id string.

    Usage::

        get_kp_id("math", "9", "s1", "ch21", "quadratic_equation_concept")
        # → "math/g9s1/ch21/quadratic_equation_concept"
    """
    return f"{domain}/g{grade}{semester}/{chapter}/{kp}"


# ─────────────────────────────────────────────────────────────────────────────
# Query functions
# ─────────────────────────────────────────────────────────────────────────────

def find_knowledge_point(kp_id: str) -> dict[str, Any] | None:
    """Look up a specific knowledge point by its kp_id.

    The kp_id includes the domain prefix (e.g. "math/..." or "chemistry/..."),
    so the correct subject is loaded automatically.

    Args:
        kp_id: e.g. "math/g9s1/ch21/quadratic_formula"
               or "chemistry/g9s1/ch01/chemical_changes"

    Returns:
        The knowledge point dict or None if not found.
    """
    parts = kp_id.split("/")
    if len(parts) < 4:
        return None

    domain = parts[0]
    data = load(subject=domain)
    if not data:
        return None

    kp_key = "/".join(parts[3:])

    for grade in data.get("grades", []):
        for sem in grade.get("semesters", []):
            for ch in sem.get("chapters", []):
                for kp in ch.get("knowledge_points", []):
                    expected = get_kp_id(
                        domain=data.get("domain", domain),
                        grade=str(grade.get("id", "")),
                        semester=sem.get("id", ""),
                        chapter=ch.get("id", ""),
                        kp=kp.get("id", ""),
                    )
                    if expected == kp_id:
                        return {
                            **kp,
                            "kp_id": kp_id,
                            "chapter_title": ch.get("title", ""),
                            "chapter_number": ch.get("number", ""),
                            "semester_name": sem.get("name", ""),
                            "grade_name": grade.get("name", ""),
                            "subject": domain,
                        }
    return None


def get_chapter_knowledge_points(chapter_id: str, subject: str = "math") -> list[dict[str, Any]]:
    """Get all knowledge points for a specific chapter within a subject.

    Args:
        chapter_id: e.g. "ch21"
        subject: Subject key, default "math"

    Returns:
        List of knowledge point dicts with kp_id filled in.
    """
    data = load(subject=subject)
    if not data:
        return []

    result: list[dict[str, Any]] = []
    for grade in data.get("grades", []):
        for sem in grade.get("semesters", []):
            for ch in sem.get("chapters", []):
                if ch.get("id") == chapter_id:
                    for kp in ch.get("knowledge_points", []):
                        kp_id = get_kp_id(
                            domain=data.get("domain", subject),
                            grade=str(grade.get("id", "")),
                            semester=sem.get("id", ""),
                            chapter=ch.get("id", ""),
                            kp=kp.get("id", ""),
                        )
                        result.append({**kp, "kp_id": kp_id})
                    return result
    return []


def get_semester_knowledge_points(semester_id: str, subject: str = "math") -> list[dict[str, Any]]:
    """Get all knowledge points for a semester within a subject."""
    data = load(subject=subject)
    if not data:
        return []
    result: list[dict[str, Any]] = []
    for grade in data.get("grades", []):
        for sem in grade.get("semesters", []):
            if sem.get("id") == semester_id:
                for ch in sem.get("chapters", []):
                    for kp in ch.get("knowledge_points", []):
                        kp_id = get_kp_id(
                            domain=data.get("domain", subject),
                            grade=str(grade.get("id", "")),
                            semester=sem.get("id", ""),
                            chapter=ch.get("id", ""),
                            kp=kp.get("id", ""),
                        )
                        result.append({**kp, "kp_id": kp_id})
                return result
    return []


def get_all_knowledge_points(subject: str | None = None) -> list[dict[str, Any]]:
    """Get ALL knowledge points for a subject.

    Args:
        subject: Subject key. If None, defaults to "math".

    Returns:
        List of knowledge point dicts with kp_id.
    """
    data = load(subject=subject)
    if not data:
        return []
    return _get_all_from(data, subject or _DEFAULT_SUBJECT)


def _get_all_from(data: dict[str, Any], domain: str) -> list[dict[str, Any]]:
    """Extract all KPs from a loaded subject dataset."""
    result: list[dict[str, Any]] = []
    for grade in data.get("grades", []):
        for sem in grade.get("semesters", []):
            for ch in sem.get("chapters", []):
                for kp in ch.get("knowledge_points", []):
                    kp_id = get_kp_id(
                        domain=data.get("domain", domain),
                        grade=str(grade.get("id", "")),
                        semester=sem.get("id", ""),
                        chapter=ch.get("id", ""),
                        kp=kp.get("id", ""),
                    )
                    result.append({**kp, "kp_id": kp_id})
    return result


def get_kp_by_importance(importance: str, subject: str = "math") -> list[dict[str, Any]]:
    """Get knowledge points filtered by importance level.

    Args:
        importance: "基础", "核心", "进阶", "应用"
        subject: Subject key.

    Returns:
        List of matching knowledge points with kp_id.
    """
    all_kps = get_all_knowledge_points(subject=subject)
    return [kp for kp in all_kps if kp.get("importance") == importance]


def get_exam_topics(subject: str = "math") -> list[dict[str, Any]]:
    """Get cross-chapter exam topic groupings for a subject."""
    data = load(subject=subject)
    if not data:
        return []
    return data.get("exam_topics", [])


# ─────────────────────────────────────────────────────────────────────────────
# Formatting (for SOUL.md injection)
# ─────────────────────────────────────────────────────────────────────────────

def format_curriculum_summary(subject: str = "math") -> str:
    """Format the curriculum as a readable text block for SOUL.md injection.

    Args:
        subject: Subject key, default "math".

    Returns a string for the teacher persona so the AI understands the
    complete course structure for the given subject.
    """
    data = load(subject=subject)
    if not data:
        return ""

    lines: list[str] = []
    lines.append(f"## {data.get('title', subject)}")
    lines.append(f"")

    for grade in data.get("grades", []):
        grade_name = grade.get("name", "")
        lines.append(f"### {grade_name}")
        lines.append(f"")
        for sem in grade.get("semesters", []):
            sem_name = sem.get("name", "")
            lines.append(f"#### {sem_name}")
            for ch in sem.get("chapters", []):
                ch_title = ch.get("title", "")
                ch_num = ch.get("number", "")
                kp_names = [kp.get("name", "") for kp in ch.get("knowledge_points", [])]
                lines.append(f"- 第{ch_num}章 {ch_title}")
                lines.append(f"  知识点：{'、'.join(kp_names)}")
            lines.append("")

    return "\n".join(lines)


def format_chapter_summary(chapter_id: str, subject: str = "math") -> str:
    """Format a single chapter's knowledge points for injection into SOUL.md.

    Args:
        chapter_id: e.g. "ch21"
        subject: Subject key, default "math"

    Returns:
        A formatted string like:
          ### 当前章节知识点
          第21章 一元二次方程
          - quadratic_equation_concept: 一元二次方程的定义
    """
    data = load(subject=subject)
    if not data:
        return ""

    for grade in data.get("grades", []):
        for sem in grade.get("semesters", []):
            for ch in sem.get("chapters", []):
                if ch.get("id") != chapter_id:
                    continue
                lines: list[str] = []
                lines.append(f"### 当前章节知识点")
                lines.append(f"{grade.get('name', '')} — 第{ch.get('number', '?')}章 {ch.get('title', '')}")
                lines.append(ch.get("description", ""))
                lines.append("")
                for kp in ch.get("knowledge_points", []):
                    kp_id = get_kp_id(
                        domain=data.get("domain", subject),
                        grade=str(grade.get("id", "")),
                        semester=sem.get("id", ""),
                        chapter=ch.get("id", ""),
                        kp=kp.get("id", ""),
                    )
                    lines.append(f"- `{kp_id}` — {kp.get('name', '')}")
                return "\n".join(lines)
    return ""
