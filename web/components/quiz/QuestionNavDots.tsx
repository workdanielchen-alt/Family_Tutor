"use client";

import { Check, X } from "lucide-react";
import type { TeachQuestion, TeachAnswerState } from "@/lib/quiz-types";

interface QuestionNavDotsProps {
  questions: TeachQuestion[];
  answers: Record<number, TeachAnswerState>;
  currentIndex: number;
  reviewMode: boolean;
  onNavigate: (index: number) => void;
  onExitReview: () => void;
}

/** Color-coded progress dots for guided quiz navigation.
 *  Green=correct, Red=wrong, Blue=current, Gray=pending.
 *  Clicking a completed dot enters review mode (read-only). */
export default function QuestionNavDots({
  questions,
  answers,
  currentIndex,
  reviewMode,
  onNavigate,
  onExitReview,
}: QuestionNavDotsProps) {
  if (questions.length === 0) return null;

  return (
    <div className="flex items-center gap-2 px-3 py-1 border-b border-[var(--border)]/30 bg-[var(--card)]/60">
      {reviewMode ? (
        <>
          <span className="text-[11px] font-medium text-amber-600 dark:text-amber-400">
            📋 回顾模式 · 第 {currentIndex + 1} 题
          </span>
          <div className="flex-1" />
          <button
            type="button"
            onClick={onExitReview}
            className="inline-flex items-center gap-1 rounded-full bg-[var(--primary)]/10 px-3 py-1 text-[11px] font-medium text-[var(--primary)] transition-colors hover:bg-[var(--primary)]/20"
          >
            返回当前题 ▶
          </button>
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5 w-full justify-center">
          {questions.map((q, i) => {
            const ans = answers[i];
            const done = ans?.submitted;
            const isCurrent = i === currentIndex;
            const isCorrect = done ? ans?.isCorrect : null;

            let dotCls =
              "flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold transition-all cursor-pointer";

            if (isCurrent) {
              dotCls +=
                " bg-[var(--primary)] text-white shadow-sm ring-2 ring-[var(--primary)]/30 scale-110";
            } else if (isCorrect === true) {
              dotCls +=
                " bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/40 dark:text-green-300";
            } else if (isCorrect === false) {
              dotCls +=
                " bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900/40 dark:text-red-300";
            } else if (done) {
              // Submitted but not auto-gradable (open-ended)
              dotCls +=
                " bg-[var(--primary)]/15 text-[var(--primary)] hover:bg-[var(--primary)]/25";
            } else {
              dotCls +=
                " bg-[var(--muted)] text-[var(--muted-foreground)] cursor-default";
            }

            return (
              <button
                key={i}
                type="button"
                disabled={!done}
                onClick={() => done && onNavigate(i)}
                className={dotCls}
                title={
                  done
                    ? isCorrect === true
                      ? `第${i + 1}题 · 答对`
                      : isCorrect === false
                        ? `第${i + 1}题 · 答错`
                        : `第${i + 1}题 · 已答`
                    : `第${i + 1}题 · 未答`
                }
              >
                {done && !isCurrent ? (
                  isCorrect === true ? (
                    <Check size={12} strokeWidth={3} />
                  ) : isCorrect === false ? (
                    <X size={12} strokeWidth={3} />
                  ) : (
                    <Check size={12} />
                  )
                ) : (
                  i + 1
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
