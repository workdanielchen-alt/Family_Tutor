"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAppShell } from "@/context/AppShellContext";
import { Loader2, Sparkles, ArrowLeft } from "lucide-react";
import { generatePractice } from "@/lib/platform-api";
import type { QuizQuestion } from "@/lib/quiz-types";
import QuizViewerChild from "@/components/quiz/QuizViewerChild";

export default function ChildQuizPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { uiMode } = useAppShell();
  const kpId = searchParams.get("kpId") || "";

  const [learnerId] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("learning-dashboard-learner-id") || "default";
    }
    return "default";
  });

  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (uiMode !== "child") router.replace("/chat");
  }, [uiMode, router]);

  const loadQuestions = useCallback(async () => {
    if (!kpId) return;
    setLoading(true);
    try {
      const result = await generatePractice(learnerId, kpId);
      const qs: QuizQuestion[] = (result.questions || []).map(
        (pq: any, i: number) => {
          const hasOptions = pq.options && Object.keys(pq.options).length > 0;
          return {
            question_id: `practice_${i}`,
            question: pq.question,
            question_type: (
              pq.question_type === "multiple_choice" || pq.question_type === "choice" || hasOptions
                ? "choice"
                : pq.question_type === "fill_in_blank"
                  ? "fill_in_blank"
                  : hasOptions ? "choice" : "short_answer"
            ) as QuizQuestion["question_type"],
            options: hasOptions ? pq.options : undefined,
            correct_answer: pq.correct_answer || "",
            explanation: pq.explanation || "",
            difficulty: pq.difficulty || "medium",
          };
        },
      );
      setQuestions(qs);
    } catch { /* ignore */ }
    setLoading(false);
  }, [kpId, learnerId]);

  useEffect(() => { if (kpId) loadQuestions(); }, [kpId, loadQuestions]);

  if (uiMode !== "child") return null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.push("/home")}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--border)] hover:bg-[var(--muted)]/40"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-[18px] font-bold text-[var(--foreground)]">
            ✏️ 巩固练习{kpId ? ` — ${kpId.split("/").pop()}` : ""}
          </h1>
        </div>
      </div>

      {!kpId ? (
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-8 text-center">
          <Sparkles size={40} className="text-[var(--muted-foreground)]/40" />
          <p className="text-[15px] text-[var(--muted-foreground)]">
            从首页选择需要练习的知识点开始做题！
          </p>
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="animate-spin" size={24} />
          <span className="ml-3 text-[14px] text-[var(--muted-foreground)]">生成练习中...</span>
        </div>
      ) : questions.length > 0 ? (
        <QuizViewerChild questions={questions} onComplete={() => router.push("/home")} language="zh" />
      ) : (
        <div className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-8 text-center">
          <p className="text-[14px] text-[var(--muted-foreground)]">暂无练习题，请稍后再试</p>
        </div>
      )}
    </div>
  );
}
