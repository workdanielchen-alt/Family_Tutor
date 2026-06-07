"use client";

import { Suspense, useEffect, useState, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  Loader2, Clock, Target, BookOpen, FileText, AlertCircle,
  Play, ChevronRight, RotateCcw, Send, GraduationCap,
} from "lucide-react";
import {
  fetchWeakPoints, fetchDueReviews, fetchExamTopics,
  generatePractice, generateExamTopic,
  fetchPracticeTeach, continueTeach,
  type WeakPoint, type DueReview, type ExamTopic, type PracticeQuestion,
} from "@/lib/platform-api";

const LEARNER_ID = "default";

type Tab = "weak" | "review" | "exam-topic";

interface ChatMessage {
  role: "teacher" | "student";
  content: string;
}

function PracticePageInner() {
  const searchParams = useSearchParams();
  const [tab, setTab] = useState<Tab>(
    (searchParams.get("tab") as Tab) || "weak",
  );
  const [weakPoints, setWeakPoints] = useState<WeakPoint[]>([]);
  const [reviews, setReviews] = useState<DueReview[]>([]);
  const [examTopics, setExamTopics] = useState<ExamTopic[]>([]);
  const [loading, setLoading] = useState(true);

  // ── Teach session state ──
  const [teachSessionId, setTeachSessionId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [answerText, setAnswerText] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [isAnswering, setIsAnswering] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [topicTitle, setTopicTitle] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [w, r, t] = await Promise.all([
          fetchWeakPoints(LEARNER_ID),
          fetchDueReviews(LEARNER_ID).then((d) => d.reviews || []),
          fetchExamTopics("math"),
        ]);
        if (!cancelled) {
          setWeakPoints(w);
          setReviews(r);
          setExamTopics(t.topics || []);
        }
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);


  // Auto-scroll + auto-focus on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  useEffect(() => {
    if (!isAnswering && !isComplete && teachSessionId) {
      inputRef.current?.focus();
    }
  }, [isAnswering, isComplete, teachSessionId]);

  const generateContextText = useCallback(
    async (generator: () => Promise<{ questions: PracticeQuestion[]; title: string }>) => {
      setIsGenerating(true);
      try {
        const result = await generator();
        const qs = result.questions || [];
        if (qs.length === 0) return null;

        // Format questions as teaching context (like a test paper)
        const lines = [
          `# ${result.title}`,
          `共 ${qs.length} 题`,
          "",
        ];
        qs.forEach((q, i) => {
          lines.push(`## 第${i + 1}题`);
          lines.push(q.question);
          if (q.options && Object.keys(q.options).length > 0) {
            const opts = Object.entries(q.options)
              .map(([k, v]) => `${k}. ${v}`)
              .join("\n");
            lines.push(opts);
          }
          lines.push("");
        });
        return lines.join("\n");
      } finally {
        setIsGenerating(false);
      }
    },
    [],
  );

  const startTeach = useCallback(
    async (contextText: string, title: string) => {
      setTopicTitle(title);
      setIsGenerating(true);
      try {
        const result = await fetchPracticeTeach(LEARNER_ID, contextText, title);
        if (result.ok && result.teach_session_id && result.first_question) {
          setTeachSessionId(result.teach_session_id);
          setChatMessages([
            { role: "teacher", content: result.first_question },
          ]);
          setCurrentQuestion(result.first_question);
          setIsComplete(false);
        }
      } catch { /* ignore */ }
      setIsGenerating(false);
    },
    [],
  );

  const handleWeakPractice = useCallback(
    async (kpId: string) => {
      const ctx = await generateContextText(() =>
        generatePractice(LEARNER_ID, kpId, 5).then((r) => ({
          questions: r.questions || [],
          title: `薄弱练习: ${kpId.split("/").pop()}`,
        })),
      );
      if (ctx) await startTeach(ctx, `薄弱练习: ${kpId.split("/").pop()}`);
    },
    [generateContextText, startTeach],
  );

  const handleReviewPractice = useCallback(
    async (kpId: string, name?: string) => {
      const ctx = await generateContextText(() =>
        generatePractice(LEARNER_ID, kpId, 3).then((r) => ({
          questions: r.questions || [],
          title: `到期复习: ${name || kpId.split("/").pop()}`,
        })),
      );
      if (ctx) await startTeach(ctx, `复习: ${name || kpId.split("/").pop()}`);
    },
    [generateContextText, startTeach],
  );

  const handleExamTopic = useCallback(
    async (topic: ExamTopic) => {
      const ctx = await generateContextText(() =>
        generateExamTopic(LEARNER_ID, topic.id, "math", 6).then((r) => ({
          questions: r.questions || [],
          title: `专题: ${r.title || topic.title}`,
        })),
      );
      if (ctx) await startTeach(ctx, topic.title);
    },
    [generateContextText, startTeach],
  );

  const handleSendAnswer = async () => {
    if (!teachSessionId || !answerText.trim() || isAnswering) return;
    const msg = answerText.trim();
    setIsAnswering(true);

    // Show student message
    setChatMessages((prev) => [...prev, { role: "student", content: msg }]);
    setAnswerText("");

    try {
      const data = await continueTeach({
        teach_session_id: teachSessionId,
        message: msg,
        learner_id: LEARNER_ID,
      });
      if (data.ok && data.reply) {
        const reply = data.reply;
        setChatMessages((prev) => [...prev, { role: "teacher", content: reply }]);
        setCurrentQuestion(reply);
        if (data.done) {
          setIsComplete(true);
          setTeachSessionId(null);
        }
      } else if (data.done) {
        setIsComplete(true);
        setTeachSessionId(null);
      }
    } catch {
      setChatMessages((prev) => [
        ...prev,
        { role: "teacher", content: "教学引擎暂时不可用，请稍后再试。" },
      ]);
      setIsComplete(true);
    }
    setIsAnswering(false);
  };

  const handleReset = () => {
    setTeachSessionId(null);
    setChatMessages([]);
    setCurrentQuestion("");
    setAnswerText("");
    setIsComplete(false);
    setIsGenerating(false);
    setIsAnswering(false);
    setTopicTitle("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendAnswer();
    }
  };

  // ── Loading states ──
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  if (isGenerating) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--primary)]" />
        <p className="text-sm text-[var(--muted-foreground)]">AI 正在准备练习题...</p>
      </div>
    );
  }

  // ── Teach Session View (chat mode) ──
  if (teachSessionId || chatMessages.length > 0) {
    return (
      <div className="flex flex-col h-[calc(100vh-12rem)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border)]/40 pb-3 mb-3">
          <button onClick={handleReset} className="text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
            ← 返回
          </button>
          <h2 className="font-semibold text-[var(--foreground)] truncate max-w-[200px]">
            {topicTitle || "引导式教学"}
          </h2>
          <div className="flex items-center gap-1">
            <GraduationCap className="h-4 w-4 text-[var(--primary)]" />
            <span className="text-xs text-[var(--muted-foreground)]">Socratic</span>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          {chatMessages.map((msg, i) => (
            <div
              key={i}
              className={`flex ${msg.role === "student" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-line ${
                  msg.role === "student"
                    ? "bg-[var(--primary)] text-white rounded-br-md"
                    : "bg-[var(--card)] border border-[var(--border)]/50 text-[var(--foreground)] rounded-bl-md"
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        {!isComplete && (
          <div className="border-t border-[var(--border)]/40 pt-3 mt-3">
            <div className="flex gap-2">
              <textarea
                ref={inputRef}
                value={answerText}
                onChange={(e) => setAnswerText(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isAnswering}
                placeholder="输入你的答案..."
                rows={2}
                className="flex-1 rounded-xl border border-[var(--border)] bg-transparent p-3 text-sm
                  placeholder:text-[var(--muted-foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30
                  resize-none"
              />
              <button
                onClick={handleSendAnswer}
                disabled={!answerText.trim() || isAnswering}
                className="rounded-xl bg-[var(--primary)] px-4 py-3 text-white disabled:opacity-50
                  flex items-center justify-center shrink-0"
              >
                {isAnswering ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <Send className="h-5 w-5" />
                )}
              </button>
            </div>
          </div>
        )}

        {isComplete && (
          <div className="border-t border-[var(--border)]/40 pt-3 mt-3">
            <button
              onClick={handleReset}
              className="w-full rounded-xl bg-[var(--primary)] py-3 text-sm font-medium text-white
                flex items-center justify-center gap-2"
            >
              <RotateCcw className="h-4 w-4" /> 返回练习
            </button>
          </div>
        )}
      </div>
    );
  }

  // ── Tab buttons ──
  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "weak", label: "薄弱", icon: <Target className="h-4 w-4" /> },
    { key: "review", label: "复习", icon: <Clock className="h-4 w-4" /> },
    { key: "exam-topic", label: "专题", icon: <BookOpen className="h-4 w-4" /> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-colors whitespace-nowrap ${
              tab === t.key
                ? "bg-[var(--primary)] text-white"
                : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* Weak Points */}
      {tab === "weak" && (
        <div className="space-y-2">
          {weakPoints.length === 0 ? (
            <div className="rounded-xl bg-[var(--card)] p-6 text-center border border-[var(--border)]/50">
              <p className="text-[var(--muted-foreground)]">暂无薄弱知识点</p>
            </div>
          ) : (
            weakPoints.map((w) => {
              const kpName = w.kp_id.split("/").pop() || w.kp_id;
              return (
                <button
                  key={w.kp_id}
                  onClick={() => handleWeakPractice(w.kp_id)}
                  className="w-full flex items-center gap-3 rounded-xl bg-[var(--card)] p-4
                    border border-[var(--border)]/50 active:scale-[0.98] transition-transform
                    hover:border-orange-300"
                >
                  <AlertCircle className="h-5 w-5 text-orange-500 shrink-0" />
                  <div className="flex-1 text-left min-w-0">
                    <p className="text-sm font-medium text-[var(--foreground)] truncate">{kpName}</p>
                    <p className="text-xs text-[var(--muted-foreground)]">
                      掌握度 {Math.round(w.level * 100)}%
                    </p>
                  </div>
                  <Play className="h-4 w-4 text-[var(--muted-foreground)]" />
                </button>
              );
            })
          )}
        </div>
      )}

      {/* Due Reviews */}
      {tab === "review" && (
        <div className="space-y-2">
          {reviews.length === 0 ? (
            <div className="rounded-xl bg-[var(--card)] p-6 text-center border border-[var(--border)]/50">
              <p className="text-[var(--muted-foreground)]">暂无到期复习</p>
            </div>
          ) : (
            reviews.map((r) => {
              const kpName = r.name || r.kp_id.split("/").pop() || r.kp_id;
              return (
                <button
                  key={r.kp_id}
                  onClick={() => handleReviewPractice(r.kp_id, r.name)}
                  className="w-full flex items-center gap-3 rounded-xl bg-[var(--card)] p-4
                    border border-[var(--border)]/50 active:scale-[0.98] transition-transform
                    hover:border-blue-300"
                >
                  <Clock className="h-5 w-5 text-blue-500 shrink-0" />
                  <div className="flex-1 text-left min-w-0">
                    <p className="text-sm font-medium text-[var(--foreground)] truncate">{kpName}</p>
                    {r.chapter_title && (
                      <p className="text-xs text-[var(--muted-foreground)]">{r.chapter_title}</p>
                    )}
                  </div>
                  <Play className="h-4 w-4 text-[var(--muted-foreground)]" />
                </button>
              );
            })
          )}
        </div>
      )}

      {/* Exam Topics */}
      {tab === "exam-topic" && (
        <div className="space-y-3">
          {examTopics.length === 0 ? (
            <div className="rounded-xl bg-[var(--card)] p-6 text-center border border-[var(--border)]/50">
              <p className="text-[var(--muted-foreground)]">暂无专题数据</p>
            </div>
          ) : (
            examTopics.map((t) => (
              <button
                key={t.id}
                onClick={() => handleExamTopic(t)}
                className="w-full rounded-xl bg-[var(--card)] p-4 text-left border border-[var(--border)]/50
                  active:scale-[0.98] transition-transform hover:border-green-300"
              >
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-[var(--foreground)]">{t.title}</p>
                  <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
                </div>
                <p className="mt-1 text-xs text-[var(--muted-foreground)] line-clamp-2">
                  {t.description}
                </p>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default function PracticePage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-[var(--muted-foreground)]" />
        </div>
      }
    >
      <PracticePageInner />
    </Suspense>
  );
}
