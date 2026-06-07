"""Snapshot current teaching state"""
import sys; sys.path.insert(0, "/app")
from provider_api import _last_tutor_context, _answer_keys, _last_question_num, _ocr_questions, _split_ocr_questions

print("=== Current State ===")
for lid in list(_last_tutor_context.keys())[-5:]:
    ctx = _last_tutor_context[lid]
    print("Learner: %s..." % lid[:40])
    print("Context length: %d" % len(ctx))
    qs = _split_ocr_questions(ctx)
    print("OCR questions: %d" % len(qs))
    for k, v in list(qs.items())[:3]:
        print("  Q%d: %s..." % (k, v[:80]))
    print("last_question_num: %s" % _last_question_num.get(lid))
    print("answer_keys: %s" % _answer_keys.get(lid, {}))
    print("_ocr_questions cached: %s" % list(_ocr_questions.get(lid, {}).keys())[:5])
    if not qs:
        print("!!! SPLIT FAILED - context preview: %s..." % ctx[:200])
