"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, MessageSquare, RotateCcw } from "lucide-react";
import type { QuizQuestion } from "@/lib/quiz-types";
import {
  isChoiceQuizQuestion,
  isConceptQuizQuestion,
  isFillInBlankQuizQuestion,
  resolveChoiceAnswerKey,
  resolveConceptAnswer,
} from "@/lib/quiz-question-type";

interface QuizViewerChildProps {
  questions: QuizQuestion[];
  /** Called when all questions are completed. */
  onComplete?: () => void;
  language?: string;
}

type AnswerState = {
  selected: string | null;
  typed: string;
  submitted: boolean;
};

const EMPTY_ANSWER: AnswerState = { selected: null, typed: "", submitted: false };

function isGradable(q: QuizQuestion): boolean {
  return isChoiceQuizQuestion(q.question_type) || isConceptQuizQuestion(q.question_type) || isFillInBlankQuizQuestion(q.question_type);
}

function getUserAnswer(q: QuizQuestion, ans: AnswerState): string {
  if (isChoiceQuizQuestion(q.question_type) || isConceptQuizQuestion(q.question_type)) {
    return ans.selected ?? "";
  }
  return ans.typed.trim();
}

function isCorrect(q: QuizQuestion, ans: AnswerState): boolean {
  const ua = getUserAnswer(q, ans);
  if (!ua) return false;
  const correct = q.correct_answer.trim();
  if (isChoiceQuizQuestion(q.question_type)) {
    const correctKey = resolveChoiceAnswerKey(correct, q.options);
    return ua.toUpperCase() === correctKey || ua.toUpperCase() === correct.charAt(0).toUpperCase();
  }
  if (isConceptQuizQuestion(q.question_type)) {
    return ua.toLowerCase() === resolveConceptAnswer(correct);
  }
  return ua.toLowerCase() === correct.toLowerCase();
}

export default function QuizViewerChild({ questions, onComplete, language = "zh" }: QuizViewerChildProps) {
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({});
  const autoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const q = questions[idx];
  const ans = answers[idx] ?? EMPTY_ANSWER;
  const total = questions.length;
  const progress = total > 0 ? ((idx + 1) / total) * 100 : 0;
  const completedCount = useMemo(() => Object.values(answers).filter(a => a.submitted).length, [answers]);
  const allDone = completedCount >= total && total > 0;
  const gradable = q ? isGradable(q) : false;
  const correct = ans.submitted && gradable ? isCorrect(q!, ans) : null;

  const updateAns = useCallback((patch: Partial<AnswerState>) => {
    setAnswers(prev => ({ ...prev, [idx]: { ...(prev[idx] ?? EMPTY_ANSWER), ...patch } }));
  }, [idx]);

  const handleSubmit = useCallback(() => {
    if (ans.submitted || !q) return;
    updateAns({ submitted: true });
  }, [ans.submitted, q, updateAns]);

  const handleReset = useCallback(() => {
    updateAns({ selected: null, typed: "", submitted: false });
  }, [updateAns]);

  // Auto-advance 1.5s after submission
  useEffect(() => {
    if (!ans.submitted) return;
    const isLast = idx >= total - 1;
    autoTimerRef.current = setTimeout(() => {
      if (isLast) {
        onComplete?.();
      } else {
        setIdx(i => i + 1);
      }
    }, 1500);
    return () => {
      if (autoTimerRef.current) clearTimeout(autoTimerRef.current);
    };
  }, [ans.submitted, idx, total, onComplete]);

  if (!q) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <p className="text-[16px] text-[var(--muted-foreground)]">暂无题目</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* ── Progress header ── */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => setIdx(i => Math.max(0, i - 1))}
          disabled={idx === 0}
          className="flex h-11 w-11 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--muted)]/40 text-[var(--foreground)] disabled:opacity-30"
          aria-label="上一题"
        >
          <ChevronLeft size={22} strokeWidth={2.5} />
        </button>
        <div className="flex-1 text-center">
          <span className="text-[15px] font-bold text-[var(--foreground)]">
            第 {idx + 1} / {total} 题
          </span>
        </div>
        <button
          type="button"
          onClick={() => setIdx(i => Math.min(total - 1, i + 1))}
          disabled={idx === total - 1}
          className="flex h-11 w-11 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--muted)]/40 text-[var(--foreground)] disabled:opacity-30"
          aria-label="下一题"
        >
          <ChevronRight size={22} strokeWidth={2.5} />
        </button>
      </div>

      {/* ── Progress bar ── */}
      <div className="h-2.5 overflow-hidden rounded-full bg-[var(--muted)]">
        <div
          className="h-full rounded-full bg-[var(--primary)] transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* ── Question number & type badge ── */}
      <div className="flex items-center gap-2">
        <span className="rounded-lg bg-[var(--primary)]/10 px-3 py-1 text-[13px] font-bold text-[var(--primary)]">
          Q{idx + 1}
        </span>
        {q.difficulty && (
          <span className={`rounded-lg px-2.5 py-1 text-[12px] font-medium ${
            q.difficulty === "hard" ? "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400"
            : q.difficulty === "medium" ? "bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
            : "bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400"
          }`}>
            {q.difficulty === "hard" ? "⭐" : q.difficulty === "easy" ? "🌱" : "📐"}
          </span>
        )}
      </div>

      {/* ── Question text ── */}
      <div className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-5">
        <p className="text-[17px] leading-relaxed text-[var(--foreground)]">
          {q.question}
        </p>
      </div>

      {/* ── Answer area ── */}
      {isChoiceQuizQuestion(q.question_type) && q.options ? (
        <div className="space-y-2.5">
          {Object.entries(q.options).map(([key, text]) => {
            const isSel = ans.selected === key;
            const correctKey = q.correct_answer.trim().charAt(0).toUpperCase();
            const isCorrectOpt = key.toUpperCase() === correctKey;
            const showFeedback = ans.submitted;

            let cls = "border-[var(--border)] bg-[var(--card)] hover:border-[var(--primary)]/40";
            if (isSel && !showFeedback) cls = "border-[var(--primary)] bg-[var(--primary)]/[0.06] ring-2 ring-[var(--primary)]/20";
            else if (showFeedback && isCorrectOpt) cls = "border-green-500 bg-green-50 dark:bg-green-950/20 dark:border-green-700";
            else if (showFeedback && isSel && !isCorrectOpt) cls = "border-red-400 bg-red-50 dark:bg-red-950/20 dark:border-red-700";

            return (
              <button
                key={key}
                disabled={ans.submitted}
                onClick={() => updateAns({ selected: key })}
                className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3.5 text-left text-[16px] transition-all ${cls}`}
              >
                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-bold ${
                  isSel && !showFeedback ? "bg-[var(--primary)] text-white"
                  : showFeedback && isCorrectOpt ? "bg-green-500 text-white"
                  : showFeedback && isSel && !isCorrectOpt ? "bg-red-400 text-white"
                  : "border-2 border-[var(--border)] text-[var(--muted-foreground)]"
                }`}>
                  {showFeedback && isCorrectOpt ? <Check size={16} /> : key}
                </span>
                <span className="text-[16px] leading-relaxed">{text}</span>
              </button>
            );
          })}
        </div>
      ) : isFillInBlankQuizQuestion(q.question_type) ? (
        <div>
          <input
            type="text"
            value={ans.typed}
            onChange={e => updateAns({ typed: e.target.value })}
            disabled={ans.submitted}
            placeholder="输入答案..."
            className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3.5 text-[16px] outline-none transition-colors focus:border-[var(--primary)]/50 disabled:bg-[var(--muted)]"
          />
        </div>
      ) : (
        <div>
          <textarea
            value={ans.typed}
            onChange={e => updateAns({ typed: e.target.value })}
            disabled={ans.submitted}
            rows={3}
            placeholder="写下你的答案..."
            className="w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3.5 text-[16px] outline-none transition-colors focus:border-[var(--primary)]/50 disabled:bg-[var(--muted)]"
          />
        </div>
      )}

      {/* ── Submit / Feedback area ── */}
      <div className="flex items-center gap-3">
        {!ans.submitted ? (
          <button
            onClick={handleSubmit}
            disabled={isChoiceQuizQuestion(q) || isConceptQuizQuestion(q) ? !ans.selected : !ans.typed.trim()}
            className="flex items-center gap-2 rounded-xl bg-[var(--primary)] px-6 py-3.5 text-[16px] font-bold text-white disabled:opacity-30"
          >
            <Check size={20} />
            检查答案
          </button>
        ) : (
          <>
            {gradable && correct !== null && (
              <div className={`flex items-center gap-2 rounded-xl px-4 py-2 text-[18px] font-bold ${
                correct ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400" : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
              }`}>
                {correct ? "🎉 答对了！" : "❌ 答错了"}
              </div>
            )}
            <button
              onClick={handleReset}
              className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] px-4 py-3 text-[14px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
            >
              <RotateCcw size={16} />
              重做
            </button>
            {ans.submitted && !allDone && (
              <button
                onClick={() => {
                  const msg = encodeURIComponent(`第${idx + 1}题：${q.question}\n我的答案：${getUserAnswer(q, ans)}\n请帮我讲解一下这道题。`);
                  window.open(`/chat?capability=chat&message=${msg}`, "_blank");
                }}
                className="flex items-center gap-1.5 rounded-xl border border-[var(--primary)]/60 bg-[var(--primary)]/10 px-4 py-3 text-[14px] font-medium text-[var(--primary)] hover:bg-[var(--primary)]/15"
              >
                <MessageSquare size={16} />
                问老师
              </button>
            )}
          </>
        )}
      </div>

      {/* ── Show correct answer after submission ── */}
      {ans.submitted && gradable && correct === false && (
        <div className="rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/20">
          <p className="mb-1 text-[13px] font-semibold text-green-700 dark:text-green-400">正确答案：</p>
          <p className="text-[16px] font-medium text-green-800 dark:text-green-300">{q.correct_answer}</p>
          {q.explanation && (
            <>
              <p className="mb-1 mt-3 text-[13px] font-semibold text-green-700 dark:text-green-400">解析：</p>
              <p className="text-[14px] leading-relaxed text-green-700 dark:text-green-300">{q.explanation}</p>
            </>
          )}
        </div>
      )}

      {ans.submitted && gradable && correct === true && q.explanation && (
        <div className="rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/20">
          <p className="text-[14px] leading-relaxed text-green-700 dark:text-green-300">{q.explanation}</p>
        </div>
      )}

      {/* ── Celebration on all done ── */}
      {allDone && (
        <div className="mt-6 text-center">
          <div className="rounded-2xl bg-gradient-to-br from-amber-100 to-orange-100 p-6 dark:from-amber-900/30 dark:to-orange-900/30">
            <p className="text-[32px]">🎉</p>
            <p className="mt-2 text-[20px] font-bold text-[var(--foreground)]">太棒了！全部完成！</p>
            <p className="mt-1 text-[14px] text-[var(--muted-foreground)]">
              你已经完成了全部 {total} 道题
            </p>
            <p className="mt-1 text-[13px] text-amber-600 dark:text-amber-400">
              ⭐ +{total * 10} 学习积分
            </p>
            <button
              onClick={onComplete}
              className="mt-4 rounded-xl bg-[var(--primary)] px-8 py-3 text-[16px] font-bold text-white hover:opacity-90"
            >
              返回首页
            </button>
          </div>
        </div>
      )}

      {/* ── Dot navigation ── */}
      <div className="flex items-center justify-center gap-1.5 py-2">
        {questions.map((_, i) => {
          const a = answers[i];
          const done = a?.submitted;
          const isCurrent = i === idx;
          let dotCls = "h-2.5 w-2.5 rounded-full transition-all";
          if (isCurrent) dotCls += " bg-[var(--primary)] w-4";
          else if (done) dotCls += " bg-green-400";
          else dotCls += " bg-[var(--muted)]";
          return <span key={i} className={dotCls} />;
        })}
      </div>
    </div>
  );
}
