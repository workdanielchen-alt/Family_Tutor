"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  Loader2,
  RefreshCw,
  AlertCircle,
  TrendingUp,
  Target,
  FileText,
  Sparkles,
  X,
  ClipboardList,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import type { LucideIcon } from "lucide-react";

import {
  fetchMasterySummary,
  fetchWeakPoints,
  fetchWrongAnswers,
  fetchWeeklyStats,
  fetchMonthlyStats,
  generatePractice,
  generateExam,
  generateReport,
  listLearners,
  type MasterySummary,
  type WeakPoint,
  type WrongAnswer,
  type PeriodStats,
} from "@/lib/platform-api";
import dynamic from "next/dynamic";
import type { QuizQuestion } from "@/lib/quiz-types";
import { QuizFollowupProvider } from "@/context/QuizFollowupContext";

const QuizViewer = dynamic(() => import("@/components/quiz/QuizViewer"), {
  ssr: false,
});

// ── Learner ID ───────────────────────────────────────────────
// Auto-detect on mount: use the first real learner, fall back to "default".
const DEFAULT_LEARNER = "default";

// ── Stat Card ────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="flex items-center gap-3.5 rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/40 text-[var(--foreground)]">
        <Icon size={18} strokeWidth={1.6} />
      </span>
      <div className="min-w-0">
        <p className="text-[13px] text-[var(--muted-foreground)]">{label}</p>
        <p className="text-xl font-semibold tracking-tight text-[var(--foreground)]">
          {value}
        </p>
        {sub && (
          <p className="text-[12px] text-[var(--muted-foreground)]">{sub}</p>
        )}
      </div>
    </div>
  );
}

// ── Day Bar (mini bar chart) ─────────────────────────────────

function DayBar({ day, count, max }: { day: string; count: number; max: number }) {
  const pct = max > 0 ? (count / max) * 100 : 0;
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-[11px] font-medium text-[var(--muted-foreground)]">
        {count}
      </span>
      <div className="relative h-16 w-6 rounded-md bg-[var(--muted)]/50">
        <div
          className="absolute bottom-0 w-full rounded-md bg-[var(--primary)]/70 transition-all"
          style={{ height: `${pct}%`, minHeight: count > 0 ? "4px" : "0px" }}
        />
      </div>
      <span className="text-[10px] text-[var(--muted-foreground)]">{day}</span>
    </div>
  );
}

// ── Practice Modal (uses DT's built-in QuizViewer) ─────────────

function PracticeModal({
  questions,
  kpId,
  onClose,
  onRegenerate,
  loading,
}: {
  questions: QuizQuestion[];
  kpId: string;
  onClose: () => void;
  onRegenerate: () => void;
  loading: boolean;
}) {
  const [showAnswers, setShowAnswers] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-[var(--border)]/60 px-5 py-3">
          <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
            练习 — {kpId.split("/").pop()}
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => { setShowAnswers(false); onRegenerate(); }}
              disabled={loading}
              className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] hover:bg-[var(--muted)]/40 disabled:opacity-40"
            >
              {loading ? "生成中..." : "重新出题"}
            </button>
            <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-[var(--muted)]/40">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="animate-spin" size={24} />
              <span className="ml-3 text-[14px] text-[var(--muted-foreground)]">正在根据你的错题生成练习...</span>
            </div>
          ) : questions.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-[var(--muted-foreground)]">
              <AlertCircle size={24} />
              <p>没有生成练习题</p>
            </div>
          ) : (
            <QuizFollowupProvider>
              <QuizViewer questions={questions} language="zh" />
            </QuizFollowupProvider>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Exam Modal (interactive QuizViewer) ────────────────────────

function ExamModal({
  examText,
  title,
  kpCovered,
  questions,
  loading,
  onClose,
  onRegenerate,
}: {
  examText: string;
  title: string;
  kpCovered: string[];
  questions: QuizQuestion[];
  loading: boolean;
  onClose: () => void;
  onRegenerate: () => void;
}) {
  const [examComplete, setExamComplete] = useState(false);

  // Loading state
  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <div className="flex items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] px-12 py-16 shadow-xl">
          <Loader2 className="animate-spin text-[var(--muted-foreground)]" size={24} />
          <span className="ml-3 text-[14px] text-[var(--muted-foreground)]">生成试卷中...</span>
        </div>
      </div>
    );
  }

  // Interactive mode: QuizViewer with structured questions
  if (questions.length > 0) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <div className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between gap-2 border-b border-[var(--border)]/60 px-5 py-3">
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-[15px] font-semibold text-[var(--foreground)]">{title}</h2>
              {kpCovered.length > 0 && (
                <p className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                  覆盖 {kpCovered.length} 个知识点
                </p>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={onRegenerate}
                disabled={loading}
                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] hover:bg-[var(--muted)]/40 disabled:opacity-40"
              >
                重新出题
              </button>
              <button
                onClick={examComplete ? onClose : undefined}
                className={`rounded-lg px-3 py-1.5 text-[12px] font-medium ${
                  examComplete
                    ? "bg-green-500 text-white hover:bg-green-600"
                    : "border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
                }`}
              >
                {examComplete ? "完成试卷 ✓" : "答题后完成"}
              </button>
              <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-[var(--muted)]/40">
                <X size={18} />
              </button>
            </div>
          </div>
          {/* Content */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
            <QuizFollowupProvider>
              <QuizViewer
                questions={questions}
                language="zh"
                autoAdvance={false}
                onComplete={() => setExamComplete(true)}
              />
            </QuizFollowupProvider>
          </div>
        </div>
      </div>
    );
  }

  // Fallback: show raw text (when API returns no parsed questions)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[80vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-[var(--foreground)]">{title}</h2>
            {kpCovered.length > 0 && (
              <p className="mt-1 text-[12px] text-[var(--muted-foreground)]">
                覆盖知识点: {kpCovered.join(", ")}
              </p>
            )}
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-[var(--muted)]/40">
            <X size={18} />
          </button>
        </div>

        <div className="whitespace-pre-wrap rounded-xl border border-[var(--border)]/60 bg-[var(--muted)]/20 p-4 text-[13px] leading-relaxed text-[var(--foreground)]">
          {examText}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-[13px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
          >
            关闭
          </button>
          <button
            onClick={onRegenerate}
            disabled={loading}
            className="rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] text-[var(--primary-foreground)] hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "生成中..." : "重新生成"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Report Modal ─────────────────────────────────────────────

function ReportModal({
  content,
  type,
  onClose,
}: {
  content: string;
  type: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--foreground)]">
            {type === "daily" ? "日报" : type === "weekly" ? "周报" : "月报"}
          </h2>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-[var(--muted)]/40">
            <X size={18} />
          </button>
        </div>
        <div className="whitespace-pre-wrap rounded-xl border border-[var(--border)]/60 bg-[var(--muted)]/20 p-4 text-[13px] leading-relaxed text-[var(--foreground)]">
          {content || "暂无学习记录"}
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={onClose}
            className="rounded-lg border border-[var(--border)] px-4 py-2 text-[13px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Collapsible Weak Points Section ──────────────────────────────

function WeakPointsSection({
  weakPoints,
  handleExam,
  handleOpenPractice,
}: {
  weakPoints: WeakPoint[];
  handleExam: () => void;
  handleOpenPractice: (kpId: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(true);
  return (
    <section className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2 text-[14px] font-medium text-[var(--foreground)]"
        >
          <ChevronDown
            size={16}
            className={`transition-transform ${collapsed ? "-rotate-90" : ""}`}
          />
          薄弱知识点（{weakPoints.length}）
        </button>
        <button
          onClick={handleExam}
          className="flex items-center gap-1.5 rounded-lg bg-amber-500 px-3 py-1.5 text-[12px] text-white hover:bg-amber-600"
        >
          <FileText size={13} />
          生成强化试卷
        </button>
      </div>
      {!collapsed && (
        <div className="mt-3 space-y-2">
          {weakPoints.map((wp) => (
            <div
              key={wp.kp_id}
              className="flex items-center justify-between rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/20 p-3"
            >
              <div className="min-w-0">
                <p className="truncate text-[13px] font-medium text-[var(--foreground)]">
                  {wp.kp_id.split("/").pop()}
                </p>
                <p className="text-[12px] text-[var(--muted-foreground)]">
                  掌握度 {Math.round(wp.level * 100)}% · 答 {wp.total} 对{" "}
                  {wp.correct}
                </p>
              </div>
              <button
                onClick={() => handleOpenPractice(wp.kp_id)}
                className="flex shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
              >
                <Sparkles size={13} />
                生成练习
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Collapsible Wrong Answers Section ────────────────────────────

function WrongAnswersSection({
  wrongAnswers,
  onPractice,
}: {
  wrongAnswers: WrongAnswer[];
  onPractice: (kpId: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(true);
  return (
    <section className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-2 text-[14px] font-medium text-[var(--foreground)]"
      >
        <ChevronDown
          size={16}
          className={`transition-transform ${collapsed ? "-rotate-90" : ""}`}
        />
        <ClipboardList size={16} />
        最近错题（{wrongAnswers.length}）
      </button>
      {!collapsed && (
        <div className="mt-3 space-y-2">
          {wrongAnswers.map((wa, i) => (
            <div
              key={i}
              className="rounded-lg border border-[var(--border)]/60 bg-[var(--muted)]/20 p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="text-[13px] leading-relaxed text-[var(--foreground)]">
                    <span className="mr-1.5 font-medium text-[var(--muted-foreground)]">#{i + 1}</span>
                    {wa.question}
                  </p>
                  <div className="flex flex-wrap gap-3 text-[12px]">
                    <span className="text-red-500">你的答案: {wa.user_answer || "-"}</span>
                    <span className="text-green-600">正确答案: {wa.correct_answer}</span>
                    <span className="text-[var(--muted-foreground)]">{wa.kp_id.split("/").pop()}</span>
                  </div>
                </div>
                <button
                  onClick={() => onPractice(wa.kp_id)}
                  className="flex shrink-0 items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
                >
                  <Sparkles size={13} />
                  巩固练习
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Main Dashboard Section ───────────────────────────────────

const LS_KEY = "learning-dashboard-learner-id";

export default function LearningDashboardSection() {
  const { t } = useTranslation();

  // Restore persisted learner ID from localStorage, fall back to "default"
  const [learnerId, setLearnerId] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem(LS_KEY) || DEFAULT_LEARNER;
    }
    return DEFAULT_LEARNER;
  });
  const [allLearners, setAllLearners] = useState<string[]>([]);
  const [summary, setSummary] = useState<MasterySummary | null>(null);
  const [weakPoints, setWeakPoints] = useState<WeakPoint[]>([]);
  const [wrongAnswers, setWrongAnswers] = useState<WrongAnswer[]>([]);
  const [weeklyStats, setWeeklyStats] = useState<PeriodStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Auto-detect learner on mount ──────────────────────────

  useEffect(() => {
    listLearners()
      .then((ids) => {
        const real = ids.filter((id) => !id.endsWith("_session"));
        if (real.length > 0) {
          setAllLearners(real);
          // If current learnerId still exists in the list, keep it.
          // Otherwise auto-select the first real learner.
          setLearnerId((prev) => (real.includes(prev) ? prev : real[0]));
        }
      })
      .catch(() => {
        /* use default fallback */
      });
  }, []);

  // ── Persist learnerId to localStorage whenever it changes ──
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem(LS_KEY, learnerId);
    }
  }, [learnerId]);

  // ── Re-fetch when learner changes ──
  useEffect(() => {
    void loadAll(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [learnerId]);

  // Modal states
  const [practiceModal, setPracticeModal] = useState<{
    kpId: string;
    questions: QuizQuestion[];
    loading: boolean;
  } | null>(null);
  const [examModal, setExamModal] = useState<{
    text: string;
    title: string;
    kps: string[];
    loading: boolean;
    questions: QuizQuestion[];
  } | null>(null);
  const [reportModal, setReportModal] = useState<{
    content: string;
    type: string;
  } | null>(null);

  // ── Data loading ──────────────────────────────────────────

  const loadAll = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    try {
      const [sum, weak, wrong, weekly] = await Promise.all([
        fetchMasterySummary(learnerId),
        fetchWeakPoints(learnerId),
        fetchWrongAnswers(learnerId, undefined, 10),
        fetchWeeklyStats(learnerId),
      ]);
      setSummary(sum);
      setWeakPoints(weak);
      setWrongAnswers(wrong);
      setWeeklyStats(weekly);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [learnerId]);

  // ── Handlers ──────────────────────────────────────────────

  const handleOpenPractice = useCallback(
    async (kpId: string) => {
      setPracticeModal({ kpId, questions: [], loading: true });
      try {
        const result = await generatePractice(learnerId, kpId);
        const questions: QuizQuestion[] = (result.questions || []).map(
          (pq, i) => {
            // options: API returns {"A":"...","B":"..."} directly
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
        setPracticeModal({ kpId, questions, loading: false });
      } catch {
        setPracticeModal({ kpId, questions: [], loading: false });
      }
    },
    [learnerId],
  );

  const handleExam = useCallback(async () => {
    setExamModal({ text: "", title: "生成中...", kps: [], loading: true, questions: [] });
    try {
      const result = await generateExam(learnerId);
      if (!result.ok) {
        setExamModal({ text: result.exam_text || "生成失败", title: result.title || "强化训练", kps: result.kp_covered || [], loading: false, questions: [] });
        return;
      }
      // Map backend ExamQuestion[] (with section_type) → QuizQuestion[]
      const sectionTypeMap: Record<string, string> = {
        "选择题": "choice",
        "填空题": "fill_in_blank",
        "解答题": "short_answer",
      };
      const quizQuestions: QuizQuestion[] = (result.questions || []).map(
        (eq, i) => ({
          question_id: `exam_${eq.num || i + 1}`,
          question: eq.question,
          question_type: (sectionTypeMap[eq.section_type] || "short_answer") as QuizQuestion["question_type"],
          options: eq.options && Object.keys(eq.options).length > 0 ? eq.options : undefined,
          correct_answer: eq.correct_answer,
          explanation: eq.explanation || "",
          difficulty: eq.difficulty || "medium",
          knowledge_context: eq.kpi || undefined,
        }),
      );
      setExamModal({
        text: result.exam_text,
        title: result.title || "强化训练",
        kps: result.kp_covered || [],
        loading: false,
        questions: quizQuestions,
      });
    } catch {
      setExamModal({ text: "生成失败", title: "强化训练", kps: [], loading: false, questions: [] });
    }
  }, [learnerId]);

  const handleReport = useCallback(async (type: "daily" | "weekly" | "monthly") => {
    setReportModal({ content: "生成中...", type });
    try {
      const text = await generateReport(learnerId, type);
      setReportModal({ content: text || "暂无学习记录", type });
    } catch {
      setReportModal({ content: "生成失败", type });
    }
  }, [learnerId]);

  // ── Render ────────────────────────────────────────────────

  // Loading state
  if (loading && !summary) {
    return (
      <div>
        <SpaceSectionHeader
          icon={BarChart3}
          title="学习进度"
          description="学习数据总览、薄弱知识点、错题本、练习与测试"
        />
        <div className="flex items-center justify-center py-20">
          <Loader2 className="animate-spin text-[var(--muted-foreground)]" size={24} />
          <span className="ml-3 text-[14px] text-[var(--muted-foreground)]">加载中...</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error && !summary) {
    return (
      <div>
        <SpaceSectionHeader
          icon={BarChart3}
          title="学习进度"
          description="学习数据总览、薄弱知识点、错题本、练习与测试"
        />
        <div className="flex flex-col items-center gap-4 rounded-xl border border-red-200 bg-red-50 p-8 text-center">
          <AlertCircle className="text-red-500" size={28} />
          <p className="text-[14px] text-red-600">{error}</p>
          <button
            onClick={() => loadAll(true)}
            className="flex items-center gap-2 rounded-lg bg-red-500 px-4 py-2 text-[13px] text-white hover:bg-red-600"
          >
            <RefreshCw size={14} />
            重试
          </button>
        </div>
      </div>
    );
  }

  // Empty state
  const isEmpty = summary && summary.total_questions === 0;

  return (
    <div>
      <SpaceSectionHeader
        icon={BarChart3}
        title="学习进度"
        description="学习数据总览、薄弱知识点、错题本、练习与测试"
        action={
          <div className="flex items-center gap-2">
            {allLearners.length > 1 && (
              <select
                value={learnerId}
                onChange={(e) => setLearnerId(e.target.value)}
                className="max-w-[160px] truncate rounded-lg border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-[12px] text-[var(--foreground)] outline-none"
              >
                {allLearners.map((id) => (
                  <option key={id} value={id}>
                    {id.includes("@") ? id.split("@")[0].slice(0, 8) + "..." : id}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={() => loadAll(true)}
              className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
            >
              <RefreshCw size={14} />
              刷新
            </button>
          </div>
        }
      />

      {isEmpty ? (
        <div className="flex flex-col items-center gap-4 rounded-xl border-2 border-dashed border-[var(--border)]/60 p-12 text-center">
          <BookOpen
            size={40}
            className="text-[var(--muted-foreground)]/50"
          />
          <p className="text-[15px] font-medium text-[var(--foreground)]">
            还没有学习记录
          </p>
          <p className="max-w-sm text-[13px] text-[var(--muted-foreground)]">
            通过微信发送作业或使用 DT 聊天开始学习，学习数据将在这里自动同步。
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* ── Overview Cards ── */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard
              icon={BookOpen}
              label="总答题数"
              value={summary?.total_questions ?? 0}
            />
            <StatCard
              icon={Target}
              label="正确率"
              value={`${summary?.accuracy ?? 0}%`}
            />
            <StatCard
              icon={TrendingUp}
              label="已掌握"
              value={summary?.mastered ?? 0}
              sub={`共 ${summary?.total_kp ?? 0} 个知识点`}
            />
            <StatCard
              icon={AlertCircle}
              label="薄弱点"
              value={weakPoints.length}
              sub={weakPoints.length > 0 ? "掌握度 < 60%" : "继续加油！"}
            />
          </div>

          {/* ── Weekly Trend ── */}
          {weeklyStats && weeklyStats.per_day.length > 0 && (
            <section className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
              <h3 className="mb-3 text-[14px] font-medium text-[var(--foreground)]">
                本周学习趋势（共 {weeklyStats.total} 题，正确率{" "}
                {weeklyStats.accuracy}%）
              </h3>
              <div className="flex items-end justify-around gap-1">
                {weeklyStats.per_day.map((d) => (
                  <DayBar
                    key={d.date}
                    day={d.date.slice(5)}
                    count={d.total}
                    max={Math.max(
                      ...weeklyStats.per_day.map((x) => x.total),
                      1,
                    )}
                  />
                ))}
              </div>
            </section>
          )}

          {/* ── Weak Points (collapsible) ── */}
          {weakPoints.length > 0 && <WeakPointsSection weakPoints={weakPoints} handleExam={handleExam} handleOpenPractice={handleOpenPractice} />}

          {/* ── Wrong Answers (collapsible) ── */}
          {wrongAnswers.length > 0 && <WrongAnswersSection wrongAnswers={wrongAnswers} onPractice={handleOpenPractice} />}

          {/* ── Report Generation ── */}
          <section className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
            <h3 className="mb-3 text-[14px] font-medium text-[var(--foreground)]">
              学习报告
            </h3>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => handleReport("daily")}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
              >
                生成日报
              </button>
              <button
                onClick={() => handleReport("weekly")}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
              >
                生成周报
              </button>
              <button
                onClick={() => handleReport("monthly")}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
              >
                生成月报
              </button>
            </div>
          </section>
        </div>
      )}

      {/* ── Modals ── */}
      {practiceModal && (
        <PracticeModal
          questions={practiceModal.questions}
          kpId={practiceModal.kpId}
          loading={practiceModal.loading}
          onClose={() => setPracticeModal(null)}
          onRegenerate={() => handleOpenPractice(practiceModal.kpId)}
        />
      )}

      {examModal && (
        <ExamModal
          examText={examModal.text}
          title={examModal.title}
          kpCovered={examModal.kps}
          questions={examModal.questions}
          loading={examModal.loading}
          onClose={() => setExamModal(null)}
          onRegenerate={handleExam}
        />
      )}

      {reportModal && (
        <ReportModal
          content={reportModal.content}
          type={reportModal.type}
          onClose={() => setReportModal(null)}
        />
      )}
    </div>
  );
}
