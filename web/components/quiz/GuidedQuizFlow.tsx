"use client";

import {
  useState,
  useCallback,
  useEffect,
  useRef,
  useMemo,
} from "react";
import {
  ArrowLeft,
  Brain,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
  MessageSquare,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import {
  isChoiceQuizQuestion,
  isConceptQuizQuestion,
  isFillInBlankQuizQuestion,
  resolveChoiceAnswerKey,
  resolveConceptAnswer,
} from "@/lib/quiz-question-type";
import type {
  TeachQuestion,
  TeachEvaluation,
  TeachAnswerState,
  KnowledgePointSummary,
} from "@/lib/quiz-types";
import QuestionNavDots from "./QuestionNavDots";
import QuestionHintPanel from "./QuestionHintPanel";
import QuizCompletionPanel from "./QuizCompletionPanel";

export interface TraceEvent {
  tool: string;
  args?: Record<string, unknown>;
  result?: string;
  label?: string;
  content?: string;
}

interface GuidedQuizFlowProps {
  questions: TeachQuestion[];
  currentIndex: number;
  answers: Record<number, TeachAnswerState>;
  evaluations: Record<number, TeachEvaluation>;
  teachSessionId: string | null;
  title: string;
  correctCount: number;
  wrongCount: number;
  isWaiting: boolean;
  isComplete: boolean;            // true when API returns done=true
  onAnswer: (answer: string, selectedOption: string | null) => Promise<void>;
  onNavigate: (index: number) => void;
  onComplete: () => void;
  onReturnHome: () => void;
  /** Paper total (e.g. 36), set once at start & never changes. */
  totalQuestions: number;
  summary?: KnowledgePointSummary;
  /** Agentic Loop trace events per question index */
  traceEvents?: Record<number, TraceEvent[]>;
}

const EMPTY_ANSWER: TeachAnswerState = {
  submitted: false,
  userAnswer: "",
  selectedOption: null,
  isCorrect: null,
};

/** Map the guided-teach question_type to the canonical QuizQuestionType
 *  that isChoiceQuizQuestion / isFillInBlankQuizQuestion understand. */
function mapQuestionType(qt: string): string {
  switch (qt) {
    case "choice":
      return "choice";
    case "fill_blank":
      return "fill_in_blank";
    case "short_answer":
    case "written":
      return "short_answer";
    default:
      return qt;
  }
}

// ── Client-side auto-grading (matches QuizViewer logic) ────────────────

function isAutoGradable(q: TeachQuestion): boolean {
  const qt = mapQuestionType(q.question_type);
  return (
    isChoiceQuizQuestion(qt) ||
    isConceptQuizQuestion(qt) ||
    isFillInBlankQuizQuestion(qt)
  );
}

function getUserAnswer(
  q: TeachQuestion,
  selectedOption: string | null,
  typedAnswer: string,
): string {
  const qt = mapQuestionType(q.question_type);
  if (isChoiceQuizQuestion(qt) || isConceptQuizQuestion(qt)) {
    return selectedOption ?? "";
  }
  return typedAnswer.trim();
}

function checkCorrect(
  q: TeachQuestion,
  selectedOption: string | null,
  typedAnswer: string,
): boolean {
  const ua = getUserAnswer(q, selectedOption, typedAnswer);
  if (!ua) return false;
  const correct = q.answer_key.trim();
  const qt = mapQuestionType(q.question_type);
  if (isChoiceQuizQuestion(qt) && q.options) {
    const correctKey = resolveChoiceAnswerKey(correct, q.options);
    return (
      ua.toUpperCase() === correctKey ||
      ua.toUpperCase() === correct.toUpperCase() ||
      ua.toUpperCase() === correct.charAt(0).toUpperCase()
    );
  }
  if (isConceptQuizQuestion(qt)) {
    return ua.toLowerCase() === resolveConceptAnswer(correct);
  }
  return ua.toLowerCase() === correct.toLowerCase();
}

// ── Tone labels per question position ──────────────────────────────────

function getPositionLabel(index: number, total: number): {
  label: string | null;
  className: string;
} {
  if (index === 0) {
    return { label: "🔥 热身题", className: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" };
  }
  if (index === total - 1) {
    return { label: "🏁 最后一题，加油！", className: "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-400" };
  }
  return { label: null, className: "" };
}

function getDifficultyLabel(d: string): { label: string; className: string } {
  switch (d) {
    case "easy":
      return { label: "🌱 简单", className: "bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400" };
    case "hard":
      return { label: "⭐ 困难", className: "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400" };
    default:
      return { label: "📐 中等", className: "bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400" };
  }
}

function getQuestionTypeLabel(qt: string): string {
  switch (qt) {
    case "choice":
      return "选择题";
    case "fill_blank":
      return "填空题";
    case "short_answer":
      return "简答题";
    case "written":
      return "写作题";
    case "concept":
      return "判断题";
    default:
      return qt;
  }
}

// ── Fill-in-the-blank inline component ─────────────────────────────────

function FillBlankCard({
  content,
  disabled,
  value,
  savedAnswer,
  onChange,
}: {
  content: string;
  disabled: boolean;
  value: string;
  savedAnswer: string;
  onChange: (v: string) => void;
}) {
  // Split on 2+ underscores.  If LLM doesn't output ___ markers, treat
  // the whole content as one blank with the question text above.
  const BLANK_RE = /_{2,}/;
  const hasBlanks = BLANK_RE.test(content);
  const parts = hasBlanks ? content.split(BLANK_RE) : [content];
  const blankCount = Math.max(1, parts.length - 1);

  // Per-blank values from comma-separated state
  const saved = (value || savedAnswer || "").split(/[,，、\s]+/).filter(Boolean);
  const blanks = saved.slice(0, blankCount);
  while (blanks.length < blankCount) blanks.push("");

  const handleChange = (idx: number, val: string) => {
    const next = [...blanks];
    next[idx] = val;
    onChange(next.filter((s) => s.trim()).join(", "));
  };

  // Auto-focus first blank on mount
  const firstRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!disabled) firstRef.current?.focus();
  }, [disabled]);

  return (
    <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-5 shadow-sm">
      {hasBlanks ? (
        <p className="text-[15px] leading-9 text-[var(--foreground)]">
          {parts.map((part, i, arr) => (
            <span key={i}>
              {part}
              {i < arr.length - 1 && (
                <input
                  type="text"
                  ref={i === 0 ? firstRef : undefined}
                  value={blanks[i]}
                  onChange={(e) => handleChange(i, e.target.value)}
                  disabled={disabled}
                  className="inline-block w-[130px] border-0 border-b-2 border-dashed border-[var(--primary)]/60 bg-[var(--primary)]/[0.04] px-2 py-0.5 text-center text-[15px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)] focus:bg-[var(--primary)]/[0.08] placeholder:text-[var(--muted-foreground)]/40 disabled:opacity-40 rounded-none"
                  placeholder={`(空 ${i + 1})`}
                />
              )}
            </span>
          ))}
        </p>
      ) : (
        // Fallback: no ___ markers — show a regular input below the question
        <div className="space-y-2">
          <p className="text-[15px] leading-relaxed text-[var(--muted-foreground)]">{content}</p>
          <input
            type="text"
            ref={firstRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            placeholder="在此填写答案"
            className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-[15px] outline-none transition-colors focus:border-[var(--primary)]/50 disabled:bg-[var(--muted)] disabled:opacity-60"
          />
        </div>
      )}
    </div>
  );
}

// ── Celebration particles ──────────────────────────────────────────────

function CelebrationOverlay({ onDone }: { onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 800);
    return () => clearTimeout(t);
  }, [onDone]);

  return (
    <div className="absolute inset-0 z-30 pointer-events-none flex items-center justify-center">
      <div className="text-center animate-bounce-in">
        <span className="text-[64px]">🎉</span>
        <p className="mt-2 text-[18px] font-bold text-green-600 dark:text-green-400">
          答对了！
        </p>
      </div>
      {/* Simple particle effect */}
      <div className="absolute inset-0 overflow-hidden">
        {Array.from({ length: 20 }).map((_, i) => (
          <span
            key={i}
            className="absolute text-[16px] animate-particle"
            style={{
              left: `${10 + Math.random() * 80}%`,
              top: `${20 + Math.random() * 60}%`,
              animationDelay: `${Math.random() * 0.8}s`,
              animationDuration: `${1 + Math.random() * 1.5}s`,
            }}
          >
            {["✨", "🌟", "💫", "🎊", "⭐"][i % 5]}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Trace Event Panel ──────────────────────────────────────────────────

function TracePanel({ events }: { events: TraceEvent[] }) {
  const [open, setOpen] = useState(false);
  if (!events.length) return null;

  const icons: Record<string, React.ReactNode> = {
    THINK: <Brain size={13} className="text-purple-500" />,
    TOOL: <BookOpen size={13} className="text-blue-500" />,
    FINISH: <MessageSquare size={13} className="text-green-500" />,
    PLAN: <Brain size={13} className="text-indigo-500" />,
  };

  return (
    <div className="mt-2 border-t border-[var(--border)]/20 pt-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Brain size={12} />
        教学推理过程 ({events.length} 步)
      </button>
      {open && (
        <div className="mt-1.5 space-y-1 rounded-lg border border-[var(--border)]/30 bg-[var(--card)]/50 p-2">
          {events.map((ev, i) => (
            <div key={i} className="flex items-start gap-2 py-1">
              <span className="mt-0.5 shrink-0">{icons[ev.label ?? ""] || <ChevronRight size={13} />}</span>
              <div className="min-w-0 flex-1 text-[12px] leading-relaxed">
                <span className="font-medium text-[var(--foreground)]">{ev.label || ev.tool}</span>
                {ev.content && (
                  <span className="ml-1 text-[var(--muted-foreground)]">{ev.content.slice(0, 200)}</span>
                )}
                {ev.result && ev.result.length > 20 && (
                  <details className="mt-0.5">
                    <summary className="cursor-pointer text-[11px] text-[var(--primary)]">查看工具结果</summary>
                    <div className="mt-0.5 rounded bg-[var(--muted)]/30 p-1.5 text-[11px] text-[var(--muted-foreground)]">
                      {ev.result.slice(0, 300)}
                    </div>
                  </details>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────

export default function GuidedQuizFlow({
  questions,
  currentIndex,
  answers,
  evaluations,
  teachSessionId,
  title,
  correctCount,
  wrongCount,
  isWaiting,
  onAnswer,
  onNavigate,
  onComplete,
  onReturnHome,
  isComplete,
  totalQuestions: paperTotal,
  summary,
  traceEvents,
}: GuidedQuizFlowProps) {
  const router = useRouter();
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [typedAnswer, setTypedAnswer] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [showCelebration, setShowCelebration] = useState(false);
  const [reviewMode, setReviewMode] = useState(false);
  const [showCompletion, setShowCompletion] = useState(false);
  const autoAdvanceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const q = questions[currentIndex];
  const ans = answers[currentIndex] ?? EMPTY_ANSWER;
  const qt = q ? mapQuestionType(q.question_type) : "short_answer";
  const isChoice = q ? isChoiceQuizQuestion(qt) : false;
  const isConcept = q ? isConceptQuizQuestion(qt) : false;
  const isFillBlank = q ? isFillInBlankQuizQuestion(qt) : false;
  const gradable = q ? isAutoGradable(q) : false;
  const completedCount = useMemo(
    () => Object.values(answers).filter((a) => a.submitted).length,
    [answers],
  );
  const allDone = isComplete && !reviewMode;

  // Sync local state from answers store when navigating
  useEffect(() => {
    if (ans.submitted) {
      setSelectedOption(ans.selectedOption);
      setTypedAnswer(ans.userAnswer);
      setSubmitted(true);
    } else {
      setSelectedOption(null);
      setTypedAnswer("");
      setSubmitted(false);
    }
  }, [currentIndex, ans.submitted, ans.selectedOption, ans.userAnswer]);

  // Cleanup auto-advance timer
  useEffect(() => {
    return () => {
      if (autoAdvanceRef.current) clearTimeout(autoAdvanceRef.current);
    };
  }, []);

  // Show completion panel when all done
  useEffect(() => {
    if (allDone && !reviewMode) {
      setShowCompletion(true);
      onComplete();
    }
  }, [allDone, reviewMode, onComplete]);

  const handleSubmit = useCallback(async () => {
    if (submitted || isWaiting || !q) return;

    const answer =
      isChoice || isConcept
        ? (selectedOption ?? "")
        : typedAnswer.trim();
    if (!answer && isChoice) return; // must select an option

    setSubmitted(true);

    // Client-side pre-judge for auto-gradable types
    let isCorrect: boolean | null = null;
    if (gradable) {
      isCorrect = checkCorrect(q, selectedOption, typedAnswer);
    }

    try {
      await onAnswer(answer, isChoice || isConcept ? selectedOption : null);

      // Celebration for correct
      if (isCorrect === true && !reviewMode) {
        setShowCelebration(true);
      }
    } catch {
      setSubmitted(false);
    }
  }, [submitted, isWaiting, q, isChoice, isConcept, selectedOption, typedAnswer, gradable, reviewMode, onAnswer]);

  // ── Auto-advance when next question arrives ──
  // After submitting a correct answer, the celebration shows for 1.5s.
  // The parent asynchronously adds the next question to the array.
  // Once it appears AND celebration is shown, we advance automatically.
  const prevQuestionCount = useRef(questions.length);
  useEffect(() => {
    if (showCelebration && questions.length > prevQuestionCount.current) {
      autoAdvanceRef.current = setTimeout(() => {
        if (currentIndex < paperTotal - 1 && currentIndex + 1 < questions.length) {
          onNavigate(currentIndex + 1);
        }
      }, 900);
    }
    prevQuestionCount.current = questions.length;
  }, [questions.length, showCelebration, currentIndex, paperTotal, onNavigate]);

  // Cancel auto-advance if the user navigates manually
  useEffect(() => {
    if (autoAdvanceRef.current) clearTimeout(autoAdvanceRef.current);
  }, [currentIndex]);

  const handleCelebrationDone = useCallback(() => {
    setShowCelebration(false);
    // Auto-advance is handled by the useEffect above —
    // it waits until the next question actually arrives in the array.
  }, []);

  const handleReset = useCallback(() => {
    setSelectedOption(null);
    setTypedAnswer("");
    setSubmitted(false);
    setShowCelebration(false);
  }, []);

  const handleNavigateTo = useCallback(
    (idx: number) => {
      // Clamp: never go past the end of loaded questions
      const safeIdx = Math.max(0, Math.min(idx, questions.length - 1));
      if (safeIdx === currentIndex) return;
      const targetAns = answers[safeIdx];
      if (targetAns?.submitted && safeIdx !== currentIndex) {
        // Enter review mode for completed question
        setReviewMode(true);
      } else {
        setReviewMode(false);
      }
      onNavigate(safeIdx);
    },
    [answers, currentIndex, questions.length, onNavigate],
  );

  const handleExitReview = useCallback(() => {
    // Find the first unanswered question
    let nextIdx = currentIndex;
    for (let i = 0; i < questions.length; i++) {
      if (!answers[i]?.submitted) {
        nextIdx = i;
        break;
      }
    }
    setReviewMode(false);
    onNavigate(nextIdx);
  }, [answers, currentIndex, questions.length, onNavigate]);

  const handleReviewMistakes = useCallback(() => {
    setShowCompletion(false);
    // Jump to first wrong answer
    for (let i = 0; i < questions.length; i++) {
      const a = answers[i];
      if (a?.submitted && a.isCorrect === false) {
        setReviewMode(true);
        onNavigate(i);
        return;
      }
    }
    // No mistakes found — go to first question
    setReviewMode(true);
    onNavigate(0);
  }, [answers, questions.length, onNavigate]);

  // ── Completion panel ──
  if (showCompletion) {
    return (
      <QuizCompletionPanel
        questions={questions}
        answers={answers}
        correctCount={correctCount}
        wrongCount={wrongCount}
        totalQuestions={paperTotal}
        summary={summary}
        onReviewMistakes={handleReviewMistakes}
        onReturnHome={onReturnHome}
      />
    );
  }

  if (!q || !teachSessionId) {
    // If we have past questions and just lost sync, go to the last valid one.
    const lastValid = Math.max(0, questions.length - 1);
    if (questions.length > 0 && currentIndex >= questions.length) {
      return (
        <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
          <p className="text-[15px] text-[var(--muted-foreground)]">
            正在加载下一题...
          </p>
          <button
            onClick={() => onNavigate(lastValid)}
            className="rounded-lg bg-[var(--primary)]/10 px-4 py-2 text-[13px] font-medium text-[var(--primary)]"
          >
            返回第 {lastValid + 1} 题
          </button>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center gap-4">
        <p className="text-[15px] text-[var(--muted-foreground)]">
          {currentIndex >= questions.length
            ? "正在加载下一题..."
            : "暂无题目，请返回重新开始"}
        </p>
        <button
          onClick={() => router.push("/chat")}
          className="rounded-lg bg-[var(--primary)]/10 px-4 py-2 text-[13px] font-medium text-[var(--primary)]"
        >
          返回首页
        </button>
      </div>
    );
  }

  const posLabel = getPositionLabel(currentIndex, paperTotal);
  const diffLabel = getDifficultyLabel(q.difficulty);
  const evalResult = evaluations[currentIndex];

  return (
    <div className="flex h-full flex-col bg-[var(--background)] relative">
      {/* ── Top bar ── */}
      <div className="shrink-0 flex items-center gap-2 border-b border-[var(--border)]/50 bg-[var(--card)]/80 px-3 py-1.5 backdrop-blur-sm">
        <button
          type="button"
          onClick={() => router.push("/chat")}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] hover:bg-[var(--muted)]"
          title="返回首页"
        >
          <ArrowLeft size={14} />
          返回
        </button>
        <span className="text-[13px] font-semibold text-[var(--foreground)] truncate flex-1">
          📋 {title || "引导式教学"}
        </span>
        <span className="text-[12px] text-[var(--muted-foreground)]/70 shrink-0">
          第 {currentIndex + 1}/{paperTotal} 题
        </span>
      </div>

      {/* ── Progress dots ── */}
      <QuestionNavDots
        questions={questions}
        answers={answers}
        currentIndex={currentIndex}
        reviewMode={reviewMode}
        onNavigate={handleNavigateTo}
        onExitReview={handleExitReview}
      />

      {/* ── Scrollable content ── */}
      <div className="flex-1 overflow-y-auto px-3 py-2 scroll-smooth">
        <div className="mx-auto max-w-[720px] space-y-2">
          {/* Position tone label */}
          {posLabel.label && !reviewMode && (
            <div
              className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-[12px] font-medium ${posLabel.className}`}
            >
              {posLabel.label}
            </div>
          )}

          {/* Review mode indicator */}
          {reviewMode && (
            <div className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-3 py-1 text-[12px] font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
              📋 回顾模式 · 只读
            </div>
          )}

          {/* Question card */}
          <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-3 shadow-sm">
            {/* Badges */}
            <div className="mb-1.5 flex flex-wrap items-center gap-1">
              <span className="rounded-md bg-[var(--muted)] px-2 py-0.5 text-[11px] font-semibold text-[var(--foreground)]">
                Q{currentIndex + 1}
              </span>
              <span className={`rounded-md px-2 py-0.5 text-[11px] font-medium ${diffLabel.className}`}>
                {diffLabel.label}
              </span>
              <span className="rounded-md bg-[var(--muted)] px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)]">
                {getQuestionTypeLabel(q.question_type)}
              </span>
              {q.knowledge_point && (
                <span className="rounded-md bg-purple-50 px-2 py-0.5 text-[10px] text-purple-600 dark:bg-purple-950/30 dark:text-purple-400">
                  📚 {q.knowledge_point.split("/").pop()}
                  {evalResult?.is_correct !== undefined && (
                    <span className="ml-1">
                      {evalResult.is_correct ? "✅" : "📖"}
                    </span>
                  )}
                </span>
              )}
            </div>

            {/* Question text */}
            <div className="text-[14px] leading-snug text-[var(--foreground)]">
              <MarkdownRenderer
                content={q.content}
                variant="prose"
                className="text-[var(--foreground)]"
              />
            </div>
          </div>

          {/* ── Answer area ── */}
          {isChoice && q.options ? (
            <div className="space-y-1.5">
              {Object.entries(q.options).map(([key, text]) => {
                const isSelected = selectedOption === key;
                const correctKey = q.answer_key.trim().charAt(0).toUpperCase();
                const isCorrectOpt = key.toUpperCase() === correctKey;
                const showFeedback = submitted;

                let cls =
                  "border-[var(--border)] bg-[var(--card)] hover:border-[var(--primary)]/40";
                if (isSelected && !showFeedback) {
                  cls =
                    "border-[var(--primary)] bg-[var(--primary)]/[0.06] ring-2 ring-[var(--primary)]/20";
                } else if (showFeedback && isCorrectOpt) {
                  cls =
                    "border-green-500 bg-green-50 dark:bg-green-950/20 dark:border-green-700";
                } else if (showFeedback && isSelected && !isCorrectOpt) {
                  cls =
                    "border-red-400 bg-red-50 dark:bg-red-950/20 dark:border-red-700";
                }

                return (
                  <button
                    key={key}
                    type="button"
                    disabled={submitted || reviewMode}
                    onClick={() => setSelectedOption(key)}
                    className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-[14px] transition-all ${cls}`}
                  >
                    <span
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[12px] font-bold ${
                        isSelected && !showFeedback
                          ? "bg-[var(--primary)] text-white"
                          : showFeedback && isCorrectOpt
                            ? "bg-green-500 text-white"
                            : showFeedback && isSelected && !isCorrectOpt
                              ? "bg-red-400 text-white"
                              : "border-2 border-[var(--border)] text-[var(--muted-foreground)]"
                      }`}
                    >
                      {showFeedback && isCorrectOpt ? (
                        <Check size={14} strokeWidth={3} />
                      ) : (
                        key
                      )}
                    </span>
                    <span className="leading-relaxed">{text}</span>
                  </button>
                );
              })}
            </div>
          ) : isConcept ? (
            <div className="grid grid-cols-2 gap-3">
              {(["true", "false"] as const).map((val) => {
                const isSelected = selectedOption === val;
                const correctTF = resolveConceptAnswer(q.answer_key);
                const isCorrect = correctTF === val;
                const showFeedback = submitted;

                let cls =
                  "border-2 border-[var(--border)] bg-[var(--card)] hover:border-[var(--primary)]/40";
                if (isSelected && !showFeedback) {
                  cls =
                    "border-[var(--primary)] bg-[var(--primary)]/[0.06] ring-2 ring-[var(--primary)]/20";
                } else if (showFeedback && isCorrect) {
                  cls =
                    "border-green-500 bg-green-50 dark:bg-green-950/20 dark:border-green-700";
                } else if (showFeedback && isSelected && !isCorrect) {
                  cls =
                    "border-red-400 bg-red-50 dark:bg-red-950/20 dark:border-red-700";
                }

                return (
                  <button
                    key={val}
                    type="button"
                    disabled={submitted || reviewMode}
                    onClick={() => setSelectedOption(val)}
                    className={`flex items-center justify-center gap-2 rounded-xl border px-4 py-4 text-[17px] font-semibold transition-all ${cls}`}
                  >
                    <span className="text-[22px]">{val === "true" ? "✓" : "✗"}</span>
                    <span>{val === "true" ? "对" : "错"}</span>
                  </button>
                );
              })}
            </div>
          ) : isFillBlank ? (
            <div className="space-y-3">
              <FillBlankCard
                content={q.content}
                disabled={submitted || reviewMode}
                value={typedAnswer}
                savedAnswer={ans.userAnswer}
                onChange={setTypedAnswer}
              />
            </div>
          ) : (
            <textarea
              value={typedAnswer}
              onChange={(e) => setTypedAnswer(e.target.value)}
              onKeyDown={(e) => {
                // Shift+Enter for newline, Enter alone submits
                if (e.key === "Enter" && !e.shiftKey && typedAnswer.trim()) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              disabled={submitted || reviewMode}
              rows={4}
              placeholder="写下你的答案……"
              className="w-full resize-none rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3.5 text-[15px] leading-relaxed outline-none transition-colors focus:border-[var(--primary)]/50 disabled:bg-[var(--muted)] disabled:opacity-60"
            />
          )}

          {/* ── Hint panel (only when not submitted and not reviewing) ── */}
          {!submitted && !reviewMode && q.hints && q.hints.length > 0 && (
            <QuestionHintPanel hints={q.hints} />
          )}

          {/* ── Submit / Feedback area ── */}
          <div className="flex items-center gap-3 flex-wrap">
            {!submitted ? (
              <button
                type="button"
                onClick={handleSubmit}
                disabled={
                  isWaiting ||
                  reviewMode ||
                  (isChoice || isConcept ? !selectedOption : !typedAnswer.trim())
                }
                className="flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-6 py-2.5 text-[15px] font-bold text-white shadow-sm transition-all hover:bg-[var(--primary)]/90 hover:shadow-md active:scale-[0.97] disabled:opacity-30 disabled:active:scale-100"
              >
                {isWaiting ? (
                  <Loader2 size={20} className="animate-spin" />
                ) : (
                  <Check size={20} />
                )}
                提交答案
              </button>
            ) : (
              <>
                {/* Client-side grade result */}
                {gradable && ans.isCorrect !== null && (
                  <div
                    className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-[16px] font-bold ${
                      ans.isCorrect
                        ? "bg-green-100 text-green-700 dark:bg-green-950/30 dark:text-green-400"
                        : "bg-red-100 text-red-700 dark:bg-red-950/30 dark:text-red-400"
                    }`}
                  >
                    {ans.isCorrect ? "🎉 答对了！" : "❌ 答错了"}
                  </div>
                )}

                {/* AI evaluation feedback */}
                {evalResult && (
                  <div
                    className={`rounded-xl px-4 py-2.5 text-[14px] leading-relaxed ${
                      evalResult.is_correct
                        ? "bg-green-50 text-green-800 dark:bg-green-950/20 dark:text-green-300 border border-green-200 dark:border-green-800"
                        : evalResult.score >= 0.5
                          ? "bg-amber-50 text-amber-800 dark:bg-amber-950/20 dark:text-amber-300 border border-amber-200 dark:border-amber-800"
                          : "bg-red-50 text-red-800 dark:bg-red-950/20 dark:text-red-300 border border-red-200 dark:border-red-800"
                    }`}
                  >
                    {evalResult.feedback}
                  </div>
                )}

                {/* Reset button */}
                {!reviewMode && (
                  <button
                    type="button"
                    onClick={handleReset}
                    className="flex items-center gap-1.5 rounded-xl border border-[var(--border)] px-4 py-2.5 text-[13px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/40"
                  >
                    <RotateCcw size={14} />
                    重做
                  </button>
                )}
              </>
            )}
          </div>

          {/* ── Agentic Loop trace events ── */}
          {traceEvents?.[currentIndex] && traceEvents[currentIndex]!.length > 0 && (
            <TracePanel events={traceEvents[currentIndex]!} />
          )}

          {/* ── Correct answer & explanation (shown on wrong) ── */}
          {submitted && ans.isCorrect === false && (
            <div className="rounded-xl border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/20">
              <p className="mb-1 text-[12px] font-semibold text-green-700 dark:text-green-400">
                正确答案：
              </p>
              <p className="text-[15px] font-medium text-green-800 dark:text-green-300">
                {q.answer_key}
              </p>
              {q.explanation && (
                <details className="mt-3" open>
                  <summary className="cursor-pointer text-[13px] font-semibold text-green-700 dark:text-green-400">
                    📖 解题步骤
                  </summary>
                  <div className="mt-2 text-[13px] leading-relaxed text-green-700 dark:text-green-300">
                    <MarkdownRenderer
                      content={q.explanation}
                      variant="prose"
                      className="text-green-700 dark:text-green-300"
                    />
                  </div>
                </details>
              )}
              {/* Also show AI evaluation explanation */}
              {evalResult?.explanation && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-[12px] font-medium text-green-700 dark:text-green-400">
                    💡 AI 讲解
                  </summary>
                  <div className="mt-2 text-[13px] leading-relaxed text-green-700 dark:text-green-300">
                    <MarkdownRenderer
                      content={evalResult.explanation}
                      variant="prose"
                      className="text-green-700 dark:text-green-300"
                    />
                  </div>
                </details>
              )}
            </div>
          )}

          {/* Mastery & KP badge in evaluation area */}
          {evalResult?.knowledge_point && (
            <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
              <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2 py-0.5 text-purple-600 dark:bg-purple-950/20 dark:text-purple-400">
                📚 {evalResult.knowledge_point.split("/").pop()}
              </span>
              {evalResult.is_correct ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-green-600 dark:bg-green-950/20 dark:text-green-400">
                  ✅ 已掌握
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-amber-600 dark:bg-amber-950/20 dark:text-amber-400">
                  📖 待巩固
                </span>
              )}
            </div>
          )}

          {/* Show explanation on correct too (collapsed) */}
          {submitted && ans.isCorrect === true && q.explanation && (
            <details className="rounded-xl border border-green-200 bg-green-50/50 p-3 dark:border-green-800 dark:bg-green-950/10">
              <summary className="cursor-pointer text-[12px] font-medium text-green-700 dark:text-green-400">
                📖 查看解题步骤
              </summary>
              <div className="mt-2 text-[13px] leading-relaxed text-green-700 dark:text-green-300">
                <MarkdownRenderer
                  content={q.explanation}
                  variant="prose"
                  className="text-green-700 dark:text-green-300"
                />
              </div>
            </details>
          )}

          {/* Review mode: show your answer */}
          {reviewMode && (
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/20">
              <p className="mb-1 text-[12px] font-semibold text-blue-700 dark:text-blue-400">
                你的答案：
              </p>
              <p className="text-[14px] text-blue-800 dark:text-blue-300">
                {ans.userAnswer || "(未作答)"}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Bottom navigation ── */}
      <div className="shrink-0 flex items-center justify-between border-t border-[var(--border)]/50 bg-[var(--card)]/80 px-3 py-2 backdrop-blur-sm">
        <button
          type="button"
          onClick={() => handleNavigateTo(Math.max(0, currentIndex - 1))}
          disabled={currentIndex === 0}
          className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <ChevronLeft size={16} />
          上一题
        </button>

        <span className="text-[12px] text-[var(--muted-foreground)]">
          {completedCount}/{paperTotal} 已完成
        </span>

        <button
          type="button"
          onClick={() => handleNavigateTo(Math.min(paperTotal - 1, currentIndex + 1))}
          disabled={
            currentIndex >= paperTotal - 1 ||
            // Cannot advance: either this question isn't submitted yet
            // (next hasn't been loaded), or the next slot doesn't exist
            (!submitted && currentIndex + 1 >= questions.length) ||
            (submitted && currentIndex + 1 >= questions.length)
          }
          className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)] disabled:opacity-30 disabled:cursor-not-allowed"
        >
          {!submitted && currentIndex + 1 >= questions.length
            ? "请先答题"
            : "下一题"}
          {!submitted && currentIndex + 1 >= questions.length ? null : (
            <ChevronRight size={16} />
          )}
        </button>
      </div>

      {/* ── Celebration overlay ── */}
      {showCelebration && <CelebrationOverlay onDone={handleCelebrationDone} />}

      {/* ── Inline CSS for particle animation ── */}
      <style jsx>{`
        @keyframes bounce-in {
          0% { transform: scale(0.3); opacity: 0; }
          50% { transform: scale(1.1); }
          70% { transform: scale(0.9); }
          100% { transform: scale(1); opacity: 1; }
        }
        .animate-bounce-in {
          animation: bounce-in 0.6s ease-out;
        }
        @keyframes particle {
          0% { transform: translateY(0) rotate(0deg) scale(1); opacity: 1; }
          100% { transform: translateY(-60px) rotate(720deg) scale(0); opacity: 0; }
        }
        .animate-particle {
          animation: particle linear forwards;
        }
      `}</style>
    </div>
  );
}
