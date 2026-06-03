"""Quiz sync: synchronize quiz results from DeepTutor to mastery tracking."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def sync_quiz_to_mastery(learner_id: str, answers: list[dict[str, Any]]) -> dict:
    """Sync a batch of quiz answers to mastery tracking.

    Each answer dict should contain:
        kp_id: knowledge point identifier
        is_correct: whether the answer was correct
        question: question text
        user_answer: the learner's answer
        correct_answer: the expected correct answer (optional)

    Returns:
        dict with 'synced' and 'errors' counts.
    """
    from domains.tutoring.mastery import update_mastery, schedule_review

    synced = 0
    errors = 0

    for ans in answers:
        kp_id = ans.get("kp_id", "")
        if not kp_id:
            errors += 1
            continue

        is_correct = ans.get("is_correct", False)
        score = 1.0 if is_correct else 0.0
        question = ans.get("question", "")
        user_answer = ans.get("user_answer", "")
        correct_answer = ans.get("correct_answer", "")

        try:
            result = update_mastery(
                learner_id=learner_id,
                kp_id=kp_id,
                correct=score,
                question=question,
                user_answer=user_answer,
                correct_answer=correct_answer,
            )
            # Schedule Ebbinghaus review
            level = result.get("level", 0.0)
            schedule_review(learner_id, kp_id, level)
            synced += 1
        except Exception as e:
            logger.error(
                "Quiz sync failed for %s / %s: %s", learner_id, kp_id, e
            )
            errors += 1

    logger.info(
        "Quiz sync: learner=%s, synced=%d, errors=%d", learner_id, synced, errors
    )
    return {"synced": synced, "errors": errors}
