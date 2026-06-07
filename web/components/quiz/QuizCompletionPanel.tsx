"use client";

import { useEffect, useRef, useState } from "react";
import { Sparkles, ArrowLeft, RotateCcw } from "lucide-react";
import type { TeachQuestion, TeachAnswerState, KnowledgePointSummary } from "@/lib/quiz-types";

interface QuizCompletionPanelProps {
  questions: TeachQuestion[];
  answers: Record<number, TeachAnswerState>;
  correctCount: number;
  wrongCount: number;
  totalQuestions: number;
  summary?: KnowledgePointSummary;
  onReviewMistakes: () => void;
  onReturnHome: () => void;
  autoReturnDelay?: number; // seconds, default 5
}

function getKpDisplayName(kpId: string): string {
  // "数学/代数/二次函数" → "二次函数"
  const parts = kpId.split("/");
  return parts[parts.length - 1] || kpId;
}

/** Completion celebration panel shown when all guided-teaching questions
 *  are answered. Shows accuracy, knowledge-point mastery bars, and
 *  auto-returns to home after a configurable delay. */
export default function QuizCompletionPanel({
  questions,
  answers,
  correctCount,
  wrongCount,
  totalQuestions,
  summary,
  onReviewMistakes,
  onReturnHome,
  autoReturnDelay = 5,
}: QuizCompletionPanelProps) {
  const [countdown, setCountdown] = useState(autoReturnDelay);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasMistakes = wrongCount > 0;
  const accuracy = totalQuestions > 0 ? Math.round((correctCount / totalQuestions) * 100) : 0;

  // Countdown timer
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          onReturnHome();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [onReturnHome]);

  // Build knowledge-point summary from questions if not provided
  const kpSummary: KnowledgePointSummary = summary || {};
  if (Object.keys(kpSummary).length === 0 && questions.length > 0) {
    for (let i = 0; i < questions.length; i++) {
      const q = questions[i];
      const kp = q.knowledge_point || "其他";
      if (!kpSummary[kp]) kpSummary[kp] = { correct: 0, total: 0 };
      kpSummary[kp].total += 1;
      if (answers[i]?.isCorrect) kpSummary[kp].correct += 1;
    }
  }

  const score = totalQuestions * 10;

  return (
    <div className="flex flex-col items-center py-8 px-4 animate-fade-in">
      {/* ── Celebration header ── */}
      <div className="text-center mb-6">
        <p className="text-[48px] leading-none mb-3">🎉</p>
        <p className="text-[24px] font-bold text-[var(--foreground)]">
          太棒了！
        </p>
        <p className="mt-1 text-[15px] text-[var(--muted-foreground)]">
          你完成了全部 {totalQuestions} 道题
        </p>
      </div>

      {/* ── Score summary ── */}
      <div className="flex items-center gap-6 mb-6">
        <div className="text-center">
          <p className="text-[13px] text-[var(--muted-foreground)]">✅ 答对</p>
          <p className="text-[28px] font-bold text-green-600 dark:text-green-400">
            {correctCount}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[13px] text-[var(--muted-foreground)]">正确率</p>
          <p
            className={`text-[28px] font-bold ${
              accuracy >= 80
                ? "text-green-600 dark:text-green-400"
                : accuracy >= 60
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-red-600 dark:text-red-400"
            }`}
          >
            {accuracy}%
          </p>
        </div>
        <div className="text-center">
          <p className="text-[13px] text-[var(--muted-foreground)]">❌ 答错</p>
          <p className="text-[28px] font-bold text-red-500 dark:text-red-400">
            {wrongCount}
          </p>
        </div>
      </div>

      {/* ── Progress bar ── */}
      <div className="w-full max-w-[360px] h-3 overflow-hidden rounded-full bg-[var(--muted)] mb-6">
        <div
          className="h-full rounded-full bg-gradient-to-r from-green-400 to-emerald-500 transition-all duration-700"
          style={{ width: `${accuracy}%` }}
        />
      </div>

      {/* ── Knowledge point summary ── */}
      {Object.keys(kpSummary).length > 0 && (
        <div className="w-full max-w-[400px] rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 mb-6">
          <p className="mb-3 text-[13px] font-semibold text-[var(--foreground)]">
            📊 知识点掌握
          </p>
          <div className="space-y-2.5">
            {Object.entries(kpSummary).map(([kpId, stats]) => {
              const rate = stats.total > 0 ? Math.round((stats.correct / stats.total) * 100) : 0;
              const isWeak = rate < 70;
              return (
                <div key={kpId} className="flex items-center gap-3">
                  <span className="w-[80px] shrink-0 text-[12px] text-[var(--foreground)] truncate">
                    {getKpDisplayName(kpId)}
                  </span>
                  <div className="flex-1 h-2 overflow-hidden rounded-full bg-[var(--muted)]">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        rate >= 80
                          ? "bg-green-400"
                          : rate >= 60
                            ? "bg-amber-400"
                            : "bg-red-400"
                      }`}
                      style={{ width: `${rate}%` }}
                    />
                  </div>
                  <span className="w-[40px] shrink-0 text-right text-[12px] font-medium text-[var(--foreground)]">
                    {rate}%
                  </span>
                  {isWeak && (
                    <span className="text-[11px] text-amber-500 dark:text-amber-400" title="薄弱知识点">
                      ⚠️
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Score reward ── */}
      <p className="mb-6 text-[14px] text-amber-600 dark:text-amber-400 font-medium">
        <Sparkles size={16} className="inline mr-1" /> +{score} 学习积分
      </p>

      {/* ── Action buttons ── */}
      <div className="flex items-center gap-3">
        {hasMistakes && (
          <button
            type="button"
            onClick={onReviewMistakes}
            className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-5 py-3 text-[14px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
          >
            <RotateCcw size={16} />
            回顾错题
          </button>
        )}
        <button
          type="button"
          onClick={onReturnHome}
          className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-3 text-[14px] font-medium text-white transition-colors hover:bg-[var(--primary)]/90 shadow-sm"
        >
          <ArrowLeft size={16} />
          返回首页
        </button>
      </div>

      {/* ── Auto-return countdown ── */}
      <p className="mt-4 text-[12px] text-[var(--muted-foreground)]/60">
        {countdown} 秒后自动返回首页
      </p>
    </div>
  );
}
