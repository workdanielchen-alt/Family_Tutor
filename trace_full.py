"""Trace full data chain: OCR → questions → answers → DT response → evaluation"""
import sys, json
sys.path.insert(0, "/app")
from provider_api import (
    _last_tutor_context, _answer_keys, _last_question_num, _ocr_questions,
    _kp_names, _last_question_text,
)

print("=" * 60)
print("FULL DATA CHAIN DUMP")
print("=" * 60)

for lid in list(_last_tutor_context.keys())[-3:]:
    print("\n--- LEARNER: %s ---" % lid[:48])

    # Step 1: OCR context
    ctx = _last_tutor_context.get(lid, "")
    print("\n[1] OCR CONTEXT (len=%d)" % len(ctx))
    print("PREVIEW: %s ..." % ctx[:300])

    # Step 2: OCR split questions
    from provider_api import _split_ocr_questions
    qs = _ocr_questions.get(lid, {}) or _split_ocr_questions(ctx)
    print("\n[2] OCR SPLIT: %d questions" % len(qs))
    for k, v in list(qs.items())[:5]:
        print("  Q%d: %s..." % (k, v[:100]))

    # Step 3: Current state
    print("\n[3] TRACKING STATE:")
    print("  last_question_num: %s" % _last_question_num.get(lid))
    print("  answer_keys: %s" % _answer_keys.get(lid, {}))
    print("  kp_names: %s" % _kp_names.get(lid, ""))
    print("  last_question_text: %s" % (_last_question_text.get(lid, "")[:80] if _last_question_text.get(lid) else "N/A"))

    # Step 4: Answer keys analysis
    keys = _answer_keys.get(lid, {})
    if keys:
        print("\n[4] ANSWER KEY ANALYSIS:")
        for k, v in sorted(keys.items()):
            print("  Key[%d] = %s" % (k, v))
        qnum = _last_question_num.get(lid, 0)
        if qnum in keys:
            print("  >>> Current q%d HAS key = %s" % (qnum, keys[qnum]))
        else:
            print("  >>> Current q%d has NO key - DT likely skipped it" % qnum)
            closest = max([k for k in keys if k < qnum], default=None)
            if closest:
                print("  >>> Closest lower key: q%d = %s" % (closest, keys[closest]))

    # Step 5: Check teach session on disk
    import os, glob
    sessions = sorted(glob.glob("/data/teach_sessions/*.json"), key=os.path.getmtime, reverse=True)
    if sessions:
        latest = sessions[0]
        with open(latest) as f:
            s = json.load(f)
        print("\n[5] LATEST SESSION: %s" % os.path.basename(latest))
        print("  status: %s" % s.get("status"))
        print("  current_question: %s" % s.get("current_question"))
        print("  total_questions: %s" % s.get("total_questions"))
        print("  correct_count: %s" % s.get("correct_count"))
        print("  wrong_count: %s" % s.get("wrong_count"))
        print("  progress: %s" % json.dumps(s.get("progress"), ensure_ascii=False)[:200] if s.get("progress") else "None")
        pq = s.get("past_questions", "")
        if pq and len(pq) > 10:
            try:
                pqs = json.loads(pq)
                print("  past_questions count: %d" % len(pqs))
                for p in pqs:
                    q = p.get("question", {})
                    e = p.get("evaluation", {})
                    print("    Q%d: answer=%s score=%s is_correct=%s" % (
                        q.get("index"), e.get("answer_key"), e.get("score"), e.get("is_correct")
                    ))
            except:
                print("  past_questions: (parse error, len=%d)" % len(pq))

print("\n" + "=" * 60)
print("END DUMP")
print("=" * 60)
