"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";
import AssistantResponse from "@/components/common/AssistantResponse";

export interface TeachingMessage {
  role: "user" | "assistant";
  content: string;
}

interface TeachingChatViewProps {
  messages: TeachingMessage[];
  onSendAnswer: (answer: string) => Promise<void>;
  isWaiting: boolean;
  onSkip?: () => void;
}

function MessageBubble({
  msg,
  isLast,
}: {
  msg: TeachingMessage;
  isLast: boolean;
}) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end px-4 py-1.5">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-[var(--primary)]/10 px-4 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] border border-[var(--primary)]/15">
          {msg.content}
        </div>
      </div>
    );
  }

  // Assistant message (question or evaluation)
  return (
    <div className={`px-4 py-3 ${isLast ? "" : "border-b border-[var(--border)]/30"}`}>
      <div className="rounded-xl bg-[var(--card)] p-4 shadow-sm border border-[var(--border)]/40">
        <div className="text-[13px] leading-relaxed text-[var(--foreground)]">
          <AssistantResponse content={msg.content} />
        </div>
      </div>
    </div>
  );
}

const MemoizedMessageBubble = memo(MessageBubble);

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

  // Auto-scroll to bottom on new messages (but only if user is near bottom)
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

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Focus input after receiving assistant reply
  useEffect(() => {
    if (!isWaiting) {
      inputRef.current?.focus();
    }
  }, [isWaiting]);

  // Extract the last assistant message as "current question"
  const lastAssistant =
    messages.length > 0 && messages[messages.length - 1].role === "assistant"
      ? messages[messages.length - 1]
      : null;

  return (
    <div className="flex h-full flex-col bg-[var(--background)]">
      {/* ── Current Question (sticky) ── */}
      {lastAssistant && (
        <div className="shrink-0 border-b border-[var(--border)]/50 bg-[var(--card)]/80 px-5 py-4 backdrop-blur-sm">
          <div className="mx-auto max-w-[800px]">
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-[var(--primary)]/10 px-2.5 py-0.5 text-[11px] font-medium text-[var(--primary)]">
                📝 当前题目
              </span>
            </div>
            <div className="text-[14px] leading-relaxed text-[var(--foreground)]">
              <AssistantResponse content={lastAssistant.content} />
            </div>
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
              // Current question is shown in the sticky header above —
              // skip it here so the user doesn't see the same text twice.
              .filter((msg) => msg !== lastAssistant)
              .map((msg, i) => (
                <MemoizedMessageBubble key={i} msg={msg} isLast={false} />
              ))
          )}
          <div ref={messagesEndRef} className="h-1" />
        </div>
      </div>

      {/* ── Answer Input ── */}
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
    </div>
  );
}
