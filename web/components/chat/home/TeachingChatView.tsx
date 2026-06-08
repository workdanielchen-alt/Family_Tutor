"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Check, X, ChevronDown, ChevronRight, Brain, BookOpen, MessageSquare } from "lucide-react";
import AssistantResponse from "@/components/common/AssistantResponse";

// ── Types ────────────────────────────────────────────────────────

export interface TraceEvent {
  tool: string;
  args?: Record<string, unknown>;
  result?: string;
  /** Agentic Loop label: THINK / TOOL / FINISH */
  label?: string;
  content?: string;
}

export interface TeachingMessage {
  role: "user" | "assistant";
  content: string;
  /** Evaluation result (EVALUATE_ANSWER phase) */
  evaluation?: {
    is_correct: boolean;
    score: number;
    feedback: string;
    answer_key: string;
    explanation?: string;
    knowledge_point?: string;
  };
  /** Current / next question structured data */
  question?: {
    index: number;
    total: number;
    question_type: string;
    content: string;
    options?: Record<string, string> | null;
    answer_key?: string;
    explanation?: string;
    hints?: string[];
    difficulty?: string;
    knowledge_point?: string;
  } | null;
  /** Agentic Loop trace events */
  trace_events?: TraceEvent[];
}

interface TeachingChatViewProps {
  messages: TeachingMessage[];
  onSendAnswer: (answer: string) => Promise<void>;
  isWaiting: boolean;
  onSkip?: () => void;
}

// ── Sub-components ───────────────────────────────────────────────

/** Choice buttons for multiple-choice questions */
function ChoiceButtons({
  options,
  disabled,
  onSelect,
}: {
  options: Record<string, string>;
  disabled: boolean;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2 pt-2">
      {Object.entries(options).map(([key, text]) => (
        <button
          key={key}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(key)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12.5px] transition-all hover:border-[var(--primary)]/40 hover:bg-[var(--primary)]/5 active:scale-95 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--primary)]/10 text-[11px] font-bold text-[var(--primary)]">
            {key}
          </span>
          <span className="text-[var(--foreground)]">{text}</span>
        </button>
      ))}
    </div>
  );
}

/** Evaluation result card (correct / wrong) */
function EvaluationBadge({ evaluation }: { evaluation: NonNullable<TeachingMessage["evaluation"]> }) {
  const isCorrect = evaluation.is_correct || evaluation.score >= 1.0;
  return (
    <div className={`mt-3 rounded-lg border p-3 text-[12.5px] ${
      isCorrect
        ? "border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950/20"
        : "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/20"
    }`}>
      <div className="mb-1 flex items-center gap-1.5 font-medium">
        {isCorrect ? (
          <><Check size={14} className="text-green-600" /><span className="text-green-700 dark:text-green-400">回答正确</span></>
        ) : (
          <><X size={14} className="text-red-600" /><span className="text-red-700 dark:text-red-400">回答有误</span></>
        )}
        {evaluation.score === 0.5 && <span className="text-amber-600 text-[11px]">（部分正确）</span>}
      </div>
      <div className="leading-relaxed text-[var(--foreground)]/80">
        {evaluation.feedback}
      </div>
      {evaluation.explanation && !isCorrect && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[11px] text-[var(--primary)] hover:underline">查看解析</summary>
          <div className="mt-1 rounded bg-[var(--card)] p-2 text-[12px] leading-relaxed">
            <AssistantResponse content={evaluation.explanation} />
          </div>
        </details>
      )}
      {evaluation.knowledge_point && (
        <div className="mt-1.5 text-[11px] text-[var(--muted-foreground)]">
          知识点：{evaluation.knowledge_point}
        </div>
      )}
    </div>
  );
}

/** Trace event panel — shows THINK→TOOL→FINISH process */
function TracePanel({ events }: { events: TraceEvent[] }) {
  const [open, setOpen] = useState(false);
  if (!events.length) return null;

  const icons: Record<string, React.ReactNode> = {
    THINK: <Brain size={13} className="text-purple-500" />,
    TOOL: <BookOpen size={13} className="text-blue-500" />,
    FINISH: <MessageSquare size={13} className="text-green-500" />,
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

// ── Message Bubble ──────────────────────────────────────────────

function MessageBubble({
  msg,
  isLast,
  onSendAnswer,
}: {
  msg: TeachingMessage;
  isLast: boolean;
  onSendAnswer: (answer: string) => Promise<void>;
}) {
  const choiceHandler = useCallback(
    (key: string) => { void onSendAnswer(key); },
    [onSendAnswer],
  );

  if (msg.role === "user") {
    return (
      <div className="flex justify-end px-4 py-1.5">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-[var(--primary)]/10 px-4 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] border border-[var(--primary)]/15">
          {msg.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className={`px-4 py-3 ${isLast ? "" : "border-b border-[var(--border)]/30"}`}>
      <div className="rounded-xl bg-[var(--card)] p-4 shadow-sm border border-[var(--border)]/40">
        {/* Main text */}
        <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
          <AssistantResponse content={msg.content} />
        </div>

        {/* Evaluation result */}
        {msg.evaluation && <EvaluationBadge evaluation={msg.evaluation} />}

        {/* Choice buttons */}
        {msg.question?.options && Object.keys(msg.question.options).length > 0 && (
          <ChoiceButtons
            options={msg.question.options}
            disabled={false}
            onSelect={choiceHandler}
          />
        )}

        {/* Trace events */}
        {msg.trace_events && <TracePanel events={msg.trace_events} />}
      </div>
    </div>
  );
}

const MemoizedMessageBubble = memo(MessageBubble);

// ── Main Component ──────────────────────────────────────────────

export function TeachingChatView({
  messages,
  onSendAnswer,
  isWaiting,
  onSkip,
}: TeachingChatViewProps) {
  const [answer, setAnswer] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(async () => {
    const trimmed = answer.trim();
    if (!trimmed || isWaiting) return;
    setAnswer("");
    await onSendAnswer(trimmed);
  }, [answer, isWaiting, onSendAnswer]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  // Auto-scroll
  const prevMsgCount = useRef(messages.length);
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const wasNearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 120;
    if (wasNearBottom || messages.length > prevMsgCount.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    prevMsgCount.current = messages.length;
  }, [messages.length]);

  useEffect(() => { inputRef.current?.focus(); }, []);
  useEffect(() => { if (!isWaiting) inputRef.current?.focus(); }, [isWaiting]);

  const lastAssistant =
    messages.length > 0 && messages[messages.length - 1].role === "assistant"
      ? messages[messages.length - 1]
      : null;

  const isChoiceQuestion = lastAssistant?.question?.options != null;
  const hasOptions = isChoiceQuestion && Object.keys(lastAssistant!.question!.options!).length > 0;

  return (
    <div className="flex h-full flex-col bg-[var(--background)]">
      {/* ── Current Question (sticky) ── */}
      {lastAssistant && (
        <div className="shrink-0 border-b border-[var(--border)]/50 bg-[var(--card)]/80 px-5 py-4 backdrop-blur-sm">
          <div className="mx-auto max-w-[800px]">
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--primary)]/10 px-2.5 py-0.5 text-[11px] font-medium text-[var(--primary)]">
                📝 当前题目
                {lastAssistant.question && (
                  <span className="text-[var(--muted-foreground)]">
                    {lastAssistant.question.index}/{lastAssistant.question.total}
                  </span>
                )}
              </span>
              {lastAssistant.question?.difficulty && (
                <span className="inline-flex items-center rounded-full bg-[var(--muted)]/50 px-2 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                  {lastAssistant.question.difficulty === "easy" ? "简单" :
                   lastAssistant.question.difficulty === "hard" ? "困难" : "中等"}
                </span>
              )}
            </div>
            <div className="text-[14px] leading-relaxed text-[var(--foreground)]">
              <AssistantResponse content={lastAssistant.content} />
            </div>
            {/* Choice buttons in sticky header */}
            {hasOptions && lastAssistant.question?.options && (
              <ChoiceButtons
                options={lastAssistant.question.options}
                disabled={isWaiting}
                onSelect={async (key) => {
                  setAnswer(key);
                  await onSendAnswer(key);
                }}
              />
            )}
            {/* Evaluation in sticky header */}
            {lastAssistant.evaluation && <EvaluationBadge evaluation={lastAssistant.evaluation} />}
          </div>
        </div>
      )}

      {/* ── Scrollable History ── */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto"
        style={{ scrollBehavior: "smooth" }}
      >
        <div className="mx-auto max-w-[800px] py-2">
          {messages.length === 0 ? (
            <div className="px-4 py-16 text-center text-[13px] text-[var(--muted-foreground)]">
              等待老师出题...
            </div>
          ) : (
            messages
              .filter((msg) => msg !== lastAssistant)
              .map((msg, i) => (
                <MemoizedMessageBubble
                  key={i}
                  msg={msg}
                  isLast={false}
                  onSendAnswer={onSendAnswer}
                />
              ))
          )}
          <div ref={messagesEndRef} className="h-1" />
        </div>
      </div>

      {/* ── Answer Input (hidden for choice questions) ── */}
      {(!isChoiceQuestion || !hasOptions) && (
        <div className="shrink-0 border-t border-[var(--border)]/50 bg-[var(--card)]/90 px-4 py-3 backdrop-blur-sm">
          <div className="mx-auto flex max-w-[800px] items-end gap-2.5">
            <div className="flex-1 rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 shadow-sm transition-colors focus-within:border-[var(--primary)]/50 focus-within:ring-1 focus-within:ring-[var(--primary)]/20">
              <textarea
                ref={inputRef}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入你的答案..."
                disabled={isWaiting}
                rows={2}
                className="w-full resize-none bg-transparent text-[14px] leading-relaxed text-[var(--foreground)] placeholder:text-[var(--muted-foreground)]/60 outline-none disabled:opacity-50"
                style={{ minHeight: "48px" }}
              />
            </div>
            <button
              onClick={handleSend}
              disabled={!answer.trim() || isWaiting}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[var(--primary)] text-white shadow-sm transition-all hover:bg-[var(--primary)]/90 hover:shadow-md active:scale-95 disabled:opacity-40 disabled:shadow-none disabled:active:scale-100"
            >
              {isWaiting ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              ) : (
                <ArrowUp size={18} />
              )}
            </button>
            <button
              onClick={onSkip}
              disabled={!onSkip}
              className="flex h-11 shrink-0 items-center gap-1 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-[12px] text-[var(--muted-foreground)]/50 transition-all hover:border-red-400/30 hover:text-red-400 hover:shadow-sm active:scale-95"
              title="跳过此题"
            >
              <span>跳过</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
