"""Mastery tracking for tutoring: knowledge point mastery, spaced repetition,
weak point analysis, and report generation.

Data is stored as JSON files in MASTERY_DIR (default: /data/mastery).
Each learner has a file named {base64(learner_id)}.json.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

MASTERY_DIR = os.getenv("MASTERY_DIR", "/data/mastery")
MASTERY_FILE = os.getenv("MASTERY_FILE", "")  # optional single-file override


def _learner_path(learner_id: str) -> str:
    b64 = base64.urlsafe_b64encode(learner_id.encode()).decode().rstrip("=")
    return os.path.join(MASTERY_DIR, f"{b64}.json")


def _load(learner_id: str) -> dict[str, Any]:
    """Load mastery data for a learner. Returns default structure if none exists."""
    path = _learner_path(learner_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load mastery for %s: %s", learner_id, e)
    return {
        "learner_id": learner_id,
        "version": 1,
        "mastery": {},
        "wrong_answers": [],
        "total_questions": 0,
        "correct_count": 0,
        "daily_stats": {},
        "answer_history": [],
        "review_schedule": {},
        "review_history": [],
        "updated_at": time.time(),
    }


def _save(data: dict[str, Any]) -> None:
    os.makedirs(MASTERY_DIR, exist_ok=True)
    path = _learner_path(data["learner_id"])
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.error("Failed to save mastery for %s: %s", data["learner_id"], e)


def get_mastery(learner_id: str, kp_id: str) -> dict[str, Any]:
    """Get mastery data for a specific knowledge point."""
    data = _load(learner_id)
    kp = data["mastery"].get(kp_id, {"level": 0.0, "total": 0, "correct": 0})
    return kp


def get_mastery_summary(learner_id: str) -> list[dict[str, Any]]:
    """Return summary of all knowledge points with mastery levels."""
    data = _load(learner_id)
    result = []
    for kp_id, kp in data["mastery"].items():
        pct = kp["correct"] / kp["total"] if kp["total"] > 0 else 0
        result.append({
            "kp_id": kp_id,
            "level": kp["level"],
            "total": kp["total"],
            "correct": kp["correct"],
            "accuracy": round(pct, 2),
        })
    return result


def update_mastery(
    learner_id: str,
    kp_id: str,
    correct: bool | float = True,
    question: str = "",
    user_answer: str = "",
    correct_answer: str = "",
) -> dict[str, Any]:
    """Record a mastery update for a knowledge point.

    ``correct`` accepts:
    - ``True`` / ``1.0`` — completely correct
    - ``0.5`` — partially correct (right idea, wrong execution)
    - ``False`` / ``0.0`` — completely wrong

    Backward compatible: old callers passing ``True``/``False`` still work.
    """
    data = _load(learner_id)
    os.makedirs(MASTERY_DIR, exist_ok=True)

    # Normalize score: bool → float.
    if isinstance(correct, bool):
        _score = 1.0 if correct else 0.0
    else:
        _score = max(0.0, min(1.0, float(correct)))

    _is_correct_bool = _score >= 1.0
    _is_partial = 0.0 < _score < 1.0
    _is_wrong = _score < 0.5  # < 0.5 counts as wrong for wrong_answers

    if kp_id not in data["mastery"]:
        data["mastery"][kp_id] = {"level": 0.0, "total": 0, "correct": 0, "partial": 0, "wrong": 0}

    kp = data["mastery"][kp_id]
    kp["total"] += 1
    if _is_correct_bool:
        kp["correct"] += 1
    elif _is_partial:
        kp["partial"] = kp.get("partial", 0) + 1
    else:
        kp["wrong"] = kp.get("wrong", 0) + 1
    # Weighted level: correct=1, partial=0.5, wrong=0
    _weighted = (kp["correct"] * 1.0 + kp.get("partial", 0) * 0.5) / kp["total"] if kp["total"] > 0 else 0.0
    kp["level"] = round(_weighted, 2)

    data["total_questions"] += 1
    if _is_correct_bool:
        data["correct_count"] += 1

    # Track wrong answers (only completely wrong answers, not partial).
    if _is_wrong:
        data["wrong_answers"].append({
            "kp_id": kp_id,
            "question": question,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "ts": time.time(),
        })
        # Keep only last 50 wrong answers
        if len(data["wrong_answers"]) > 50:
            data["wrong_answers"] = data["wrong_answers"][-50:]

    # Answer history
    data["answer_history"].append({
        "kp_id": kp_id,
        "question": question,
        "user_answer": user_answer,
        "correct_answer": correct_answer,
        "is_correct": _is_correct_bool,
        "score": _score,
        "ts": time.time(),
    })
    if len(data["answer_history"]) > 200:
        data["answer_history"] = data["answer_history"][-200:]

    # Daily stats
    today = date.today().isoformat()
    if today not in data["daily_stats"]:
        data["daily_stats"][today] = {"total": 0, "correct": 0, "wrong": 0, "partial": 0, "weak_points": []}
    ds = data["daily_stats"][today]
    ds["total"] += 1
    if _is_correct_bool:
        ds["correct"] += 1
    elif _is_partial:
        ds["partial"] = ds.get("partial", 0) + 1
    else:
        ds["wrong"] += 1
        if kp_id not in ds["weak_points"]:
            ds["weak_points"].append(kp_id)

    data["updated_at"] = time.time()
    _save(data)
    return kp


def get_wrong_answers(
    learner_id: str,
    kp_id: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get wrong answers for a learner, optionally filtered by kp_id."""
    data = _load(learner_id)
    wrongs = data.get("wrong_answers", [])
    if kp_id:
        wrongs = [w for w in wrongs if w.get("kp_id") == kp_id]
    return wrongs[-limit:]


def weak_points(learner_id: str) -> list[dict[str, Any]]:
    """Get weak knowledge points (level < 0.6)."""
    data = _load(learner_id)
    points = []
    for kp_id, kp in data["mastery"].items():
        if kp["level"] < 0.6 and kp["total"] > 0:
            points.append({
                "kp_id": kp_id,
                "level": kp["level"],
                "total": kp["total"],
            })
    points.sort(key=lambda x: x["level"])
    return points


def get_due_reviews(learner_id: str) -> list[dict[str, Any]]:
    """Get knowledge points due for review (Ebbinghaus spaced repetition)."""
    data = _load(learner_id)
    today = date.today().isoformat()
    due = []
    for kp_id, due_date in data.get("review_schedule", {}).items():
        if due_date <= today:
            kp = data["mastery"].get(kp_id, {"level": 0.0})
            due.append({
                "kp_id": kp_id,
                "level": kp.get("level", 0.0),
                "due_date": due_date,
            })
    due.sort(key=lambda x: x["due_date"])
    return due


def schedule_review(learner_id: str, kp_id: str, level: float) -> None:
    """Schedule a review for a knowledge point based on its mastery level.

    Ebbinghaus intervals: 1d, 3d, 7d, 14d, 30d
    Lower mastery → shorter interval.
    """
    data = _load(learner_id)
    if level < 0.3:
        interval = 1
    elif level < 0.6:
        interval = 3
    elif level < 0.8:
        interval = 7
    elif level < 0.9:
        interval = 14
    else:
        interval = 30

    due = date.today()
    from datetime import timedelta
    due_str = (due + timedelta(days=interval)).isoformat()
    data["review_schedule"][kp_id] = due_str
    data["review_history"].append({
        "kp_id": kp_id,
        "level": level,
        "scheduled": due_str,
        "ts": time.time(),
    })
    data["updated_at"] = time.time()
    _save(data)


def get_answer_history(
    learner_id: str,
    limit: int = 20,
    kp_id: str = "",
) -> list[dict[str, Any]]:
    """Get answer history for a learner."""
    data = _load(learner_id)
    history = data.get("answer_history", [])
    if kp_id:
        history = [h for h in history if h.get("kp_id") == kp_id]
    return history[-limit:]


def get_weekly_stats(learner_id: str) -> dict[str, Any]:
    """Get statistics for the last 7 days."""
    data = _load(learner_id)
    today = date.today()
    from datetime import timedelta
    week_ago = (today - timedelta(days=7)).isoformat()
    stats = {}
    total = correct = wrong = 0
    for day_str, ds in data.get("daily_stats", {}).items():
        if day_str >= week_ago:
            stats[day_str] = ds
            total += ds["total"]
            correct += ds["correct"]
            wrong += ds["wrong"]
    return {
        "daily": stats,
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "accuracy": round(correct / total, 2) if total > 0 else 0,
    }


def get_monthly_stats(learner_id: str) -> dict[str, Any]:
    """Get statistics for the last 30 days."""
    data = _load(learner_id)
    today = date.today()
    from datetime import timedelta
    month_ago = (today - timedelta(days=30)).isoformat()
    stats = {}
    total = correct = wrong = 0
    for day_str, ds in data.get("daily_stats", {}).items():
        if day_str >= month_ago:
            stats[day_str] = ds
            total += ds["total"]
            correct += ds["correct"]
            wrong += ds["wrong"]
    return {
        "daily": stats,
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "accuracy": round(correct / total, 2) if total > 0 else 0,
    }


# ── K9 Motivational System ─────────────────────────────────────


def _today_str() -> str:
    return date.today().isoformat()


def _get_level(points: int) -> int:
    """Return learning level: floor(sqrt(points/100)) + 1, capped at 100."""
    return min(100, int((points / 100) ** 0.5) + 1) if points > 0 else 1


def _get_xp_to_next(points: int) -> int:
    """Return XP needed for next level."""
    level = _get_level(points)
    next_level_points = (level ** 2) * 100
    return next_level_points - points


_ACHIEVEMENT_DEFS: list[dict] = [
    {"id": "first_answer",     "name": "第一次答题",     "condition": lambda d: d.get("total_questions", 0) >= 1,                "points": 10},
    {"id": "ten_answers",      "name": "答题数破10",    "condition": lambda d: d.get("total_questions", 0) >= 10,              "points": 20},
    {"id": "fifty_answers",    "name": "答题数破50",    "condition": lambda d: d.get("total_questions", 0) >= 50,              "points": 50},
    {"id": "streak_3",         "name": "连续学习3天",   "condition": lambda d: d.get("streak", {}).get("current", 0) >= 3,     "points": 30},
    {"id": "streak_7",         "name": "学习满一周",     "condition": lambda d: d.get("streak", {}).get("current", 0) >= 7,    "points": 50},
    {"id": "weak_point_first", "name": "首次攻克薄弱点", "condition": lambda d: _check_weak_point_conquered(d),              "points": 40},
    {"id": "perfect_session",  "name": "全对的一天",    "condition": lambda d: _check_perfect_session(d),                     "points": 30},
    {"id": "mastery_90",       "name": "掌握度突破90%", "condition": lambda d: any(k["level"] >= 0.9 for k in d.get("mastery", {}).values()), "points": 50},
    {"id": "five_days_week",   "name": "每周学习5天",   "condition": lambda d: _check_weekly_days(d, 5),                      "points": 60},
]


def _check_weak_point_conquered(data: dict) -> bool:
    """Check if any weak point (< 0.6) has been conquered (>= 0.6)."""
    for kp_id, kp in data.get("mastery", {}).items():
        if kp.get("level", 0) >= 0.6 and kp.get("total", 0) >= 3:
            return True
    return False


def _check_perfect_session(data: dict) -> bool:
    """Check if today was a perfect session (all correct, >= 3 questions)."""
    today = _today_str()
    ds = data.get("daily_stats", {}).get(today, {})
    total = ds.get("total", 0)
    correct = ds.get("correct", 0)
    return total >= 3 and correct == total


def _check_weekly_days(data: dict, target: int) -> bool:
    """Check if learner studied at least ``target`` days this week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days_count = 0
    for i in range((today - monday).days + 1):
        day_str = (monday + timedelta(days=i)).isoformat()
        ds = data.get("daily_stats", {}).get(day_str, {})
        if ds.get("total", 0) > 0:
            days_count += 1
    return days_count >= target


def update_streak(learner_id: str) -> None:
    """Update consecutive-study streak. Call after each teaching interaction."""
    data = _load(learner_id)
    today = _today_str()
    streak = data.setdefault("streak", {})
    last = streak.get("last_active", "")

    if last == today:
        _save(data)
        return

    if last == (date.today() - timedelta(days=1)).isoformat():
        streak["current"] = streak.get("current", 0) + 1
    elif last != today:
        streak["current"] = 1

    streak["longest"] = max(streak.get("longest", 0), streak["current"])
    streak["last_active"] = today

    data["points"] = data.get("points", 0) + 5
    data["level"] = _get_level(data["points"])
    _check_achievements(data)
    _save(data)


def add_points(learner_id: str, amount: int) -> None:
    """Add learning points."""
    data = _load(learner_id)
    data["points"] = data.get("points", 0) + amount
    data["level"] = _get_level(data["points"])
    _check_achievements(data)
    _save(data)


def _check_achievements(data: dict) -> list[str]:
    """Check and unlock achievements. Returns newly unlocked IDs."""
    unlocked = data.setdefault("achievements", [])
    unlocked_ids = {a["id"] for a in unlocked}
    newly_unlocked: list[str] = []

    for ach in _ACHIEVEMENT_DEFS:
        if ach["id"] in unlocked_ids:
            continue
        try:
            if ach["condition"](data):
                unlocked.append({"id": ach["id"], "name": ach["name"], "unlocked_at": time.time()})
                unlocked_ids.add(ach["id"])
                newly_unlocked.append(ach["id"])
                data["points"] = data.get("points", 0) + ach["points"]
        except Exception:
            continue

    if newly_unlocked:
        data["level"] = _get_level(data["points"])
        logger.info("Achievements unlocked for %s: %s", data.get("learner_id"), newly_unlocked)
    return newly_unlocked


def get_motivation_info(learner_id: str) -> dict:
    """Get motivational info for SOUL.md injection."""
    data = _load(learner_id)
    streak = data.get("streak", {})
    points = data.get("points", 0)
    level = _get_level(points)
    achievements = data.get("achievements", [])

    weekly = get_weekly_stats(learner_id)
    last_week_accuracy = 0
    if weekly and weekly.get("total", 0) > 0:
        lw_date = (date.today() - timedelta(days=7)).isoformat()
        lw_ds = data.get("daily_stats", {}).get(lw_date, {})
        lw_total = lw_ds.get("total", 0)
        lw_correct = lw_ds.get("correct", 0)
        if lw_total > 0:
            last_week_accuracy = round(lw_correct / lw_total * 100)

    return {
        "streak_current": streak.get("current", 0),
        "streak_longest": streak.get("longest", 0),
        "points": points,
        "level": level,
        "xp_to_next": _get_xp_to_next(points),
        "achievement_count": len(achievements),
        "weekly_accuracy": weekly.get("accuracy", 0) if weekly else 0,
        "last_week_accuracy": last_week_accuracy,
    }


def generate_daily_report(
    learner_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Generate a daily learning report from mastery data."""
    today = date.today().isoformat()
    ds = data.get("daily_stats", {}).get(today, {"total": 0, "correct": 0, "wrong": 0, "weak_points": []})

    weak = []
    for wp in ds.get("weak_points", []):
        kp = data["mastery"].get(wp, {})
        weak.append({
            "kp_id": wp,
            "level": kp.get("level", 0),
            "total": kp.get("total", 0),
        })

    return {
        "summary": {
            "total_questions": ds.get("total", 0),
            "correct": ds.get("correct", 0),
            "wrong": ds.get("wrong", 0),
            "accuracy": round(ds.get("correct", 0) / max(ds.get("total", 0), 1), 2),
        },
        "weak_points": weak,
        "learner_id": learner_id,
        "date": today,
    }


def generate_parent_report(learner_id: str, days: int = 7) -> dict[str, Any]:
    """Generate a parent-facing report for daily/weekly/monthly overview."""
    data = _load(learner_id)
    daily = data.get("daily_stats", {})
    answer_history = data.get("answer_history", [])

    # Filter daily_stats by time window
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent_days = {k: v for k, v in daily.items() if k >= cutoff}

    total_q = sum(d.get("total", 0) for d in recent_days.values())
    correct_q = sum(d.get("correct", 0) for d in recent_days.values())
    wrong_q = sum(d.get("wrong", 0) for d in recent_days.values())
    weak = set()
    for d in recent_days.values():
        weak.update(d.get("weak_points", []))
    weak_list = sorted(weak)

    # Filter answer_history by time window
    recent_answers = [
        a for a in answer_history
        if isinstance(a.get("timestamp"), str) and a["timestamp"] >= cutoff
    ]

    return {
        "learner_id": learner_id,
        "period_days": days,
        "summary": {
            "total_questions": total_q,
            "correct_count": correct_q,
            "wrong_count": wrong_q,
            "accuracy": round(correct_q / total_q, 2) if total_q > 0 else 0,
        },
        "weak_points": weak_list,
        "recent_wrong": [
            a for a in recent_answers if not a.get("correct", True)
        ][:5],
        "mastery_count": len(data.get("mastery", {})),
    }
