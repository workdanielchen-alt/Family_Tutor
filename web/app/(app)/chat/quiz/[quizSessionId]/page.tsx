"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, Loader2, AlertCircle } from "lucide-react";
import dynamic from "next/dynamic";
import { QuizFollowupProvider } from "@/context/QuizFollowupContext";
import { fetchQuizSession, completeQuizSession } from "@/lib/platform-api";
import type { QuizQuestion } from "@/lib/quiz-types";

const QuizViewer = dynamic(() => import("@/components/quiz/QuizViewer"), {
  ssr: false,
});

export default function ChatQuizPage() {
  const params = useParams<{ quizSessionId: string }>();
  const router = useRouter();
  const quizSessionId = params.quizSessionId ?? null;

  const [sessionData, setSessionData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);

  // ── Load quiz session ──
  useEffect(() => {
    if (!quizSessionId) {
      router.replace("/chat");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchQuizSession(quizSessionId);
        if (!cancelled) {
          setSessionData(data);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载失败");
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [quizSessionId, router]);

  // ── Map to QuizQuestion[] ──
  const questions: QuizQuestion[] = useMemo(() => {
    if (!sessionData?.questions) return [];
    return sessionData.questions.map((q: any, i: number) => ({
      question_id: q.question_id || `q_${i}`,
      question: q.question,
      question_type: q.question_type || "choice",
      options: q.options && Object.keys(q.options).length > 0 ? q.options : undefined,
      correct_answer: q.correct_answer || "",
      explanation: q.explanation || "",
      difficulty: q.difficulty || "medium",
      knowledge_context: q.knowledge_context || undefined,
    }));
  }, [sessionData]);

  const learnerId = sessionData?.learner_id || "default";

  // ── Complete session → back to chat ──
  const handleComplete = () => {
    setCompleted(true);
    completeQuizSession(quizSessionId!, learnerId).catch(() => {});
  };

  // ── Render ──

  // Loading
  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[var(--background)]">
        <Loader2 className="animate-spin text-[var(--muted-foreground)]" size={24} />
        <span className="ml-3 text-[14px] text-[var(--muted-foreground)]">加载试卷中...</span>
      </div>
    );
  }

  // Error
  if (error || !sessionData) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-[var(--background)]">
        <AlertCircle className="text-red-500" size={32} />
        <p className="text-[14px] text-[var(--foreground)]">{error || "无法加载试卷"}</p>
        <button
          onClick={() => router.push("/chat")}
          className="rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] text-white"
        >
          返回聊天
        </button>
      </div>
    );
  }

  // Empty
  if (questions.length === 0) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-[var(--background)]">
        <p className="text-[14px] text-[var(--muted-foreground)]">试卷暂无题目</p>
        <button
          onClick={() => router.push("/chat")}
          className="rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] text-white"
        >
          返回聊天
        </button>
      </div>
    );
  }

  // Completed
  if (completed) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-[var(--background)]">
        <p className="text-lg font-semibold text-[var(--foreground)]">试卷已完成 🎉</p>
        <p className="text-[13px] text-[var(--muted-foreground)]">
          {sessionData.title || "练习"} · {sessionData.total_questions} 题
        </p>
        <button
          onClick={() => router.push("/chat")}
          className="rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] text-white"
        >
          返回聊天
        </button>
      </div>
    );
  }

  // QuizViewer — 试卷模式
  return (
    <div className="mx-auto flex h-screen max-w-4xl flex-col bg-[var(--background)]">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-[var(--border)]/60 px-4 py-3">
        <button
          onClick={() => router.push("/chat")}
          className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[15px] font-semibold text-[var(--foreground)]">
            {sessionData.title || "微信试卷"}
          </h1>
          <p className="text-[11px] text-[var(--muted-foreground)]">
            {sessionData.total_questions} 题 · 已完成 {sessionData.completed}/{sessionData.total_questions}
          </p>
        </div>
      </div>

      {/* QuizViewer — autoAdvance 默认开启，答完自动切下一题 */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <QuizFollowupProvider>
          <QuizViewer
            questions={questions}
            sessionId={quizSessionId}
            language="zh"
            onComplete={handleComplete}
          />
        </QuizFollowupProvider>
      </div>
    </div>
  );
}
