"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useAppShell } from "@/context/AppShellContext";
import { fetchPendingTasks, type PendingTask } from "@/lib/platform-api";

const SOURCE_ICONS: Record<string, string> = {
  wechat: "📱",
  web_upload: "💻",
  auto_generated: "🤖",
  webui: "💻",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待开始",
  active: "进行中",
};

export default function PendingTasksBanner() {
  const { t } = useTranslation();
  const router = useRouter();
  const { sidebarCollapsed: collapsed } = useAppShell();
  const [tasks, setTasks] = useState<PendingTask[]>([]);

  useEffect(() => {
    fetchPendingTasks()
      .then((data) => setTasks(data.tasks || []))
      .catch(() => { /* silent */ });
  }, []);

  if (tasks.length === 0) return null;

  const handleStartTask = (task: PendingTask) => {
    // Dispatch CustomEvent so the chat page picks it up even when
    // already mounted (same-page nav via router.push may not remount).
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("start-teach", { detail: task.teach_session_id }),
      );
    }
    // Also navigate — handles cross-page case (user on /co-writer etc.)
    if (task.dt_session_id) {
      router.push(`/chat/${task.dt_session_id}`);
    } else {
      router.push(`/chat?teach=${task.teach_session_id}`);
    }
  };

  if (collapsed) {
    return (
      <div className="flex w-full flex-col items-center gap-0.5 px-1">
        {tasks.slice(0, 3).map((task) => (
          <button
            key={task.teach_session_id}
            onClick={() => handleStartTask(task)}
            title={task.title}
            className="relative flex h-9 w-9 items-center justify-center rounded-xl text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-[var(--foreground)]"
          >
            <span className="text-[14px]">
              {SOURCE_ICONS[task.task_source] || "📄"}
            </span>
            {task.total_questions > 0 && (
              <span className="absolute -bottom-0.5 -right-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[var(--primary)] px-1 text-[9px] font-medium text-white">
                {task.total_questions}
              </span>
            )}
          </button>
        ))}
        {tasks.length > 3 && (
          <span className="text-[10px] text-[var(--muted-foreground)]/40">
            +{tasks.length - 3}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="border-b border-[var(--border)]/20 pb-1">
      <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-[var(--muted-foreground)]/50">
        📋 {t("Pending tasks")}
      </div>
      {tasks.map((task) => {
        const icon = SOURCE_ICONS[task.task_source] || "📄";
        const statusLabel = STATUS_LABELS[task.status] || "";
        const total = task.total_questions || 1;
        const current = task.current_question || 0;
        const pct = Math.min(100, Math.round((current / total) * 100));

        return (
          <button
            key={task.teach_session_id}
            onClick={() => handleStartTask(task)}
            className="group flex w-full items-center gap-2 rounded-r-lg py-1.5 pl-3 pr-2 text-left transition-colors hover:bg-[var(--background)]/40"
          >
            <span className="shrink-0 text-[14px]">{icon}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="truncate text-[12px] text-[var(--foreground)]/90">
                  {task.title}
                </span>
                {statusLabel && (
                  <span className="shrink-0 rounded-full bg-[var(--primary)]/10 px-1.5 py-px text-[9px] text-[var(--primary)]">
                    {statusLabel}
                  </span>
                )}
              </div>
              {task.total_questions > 0 && (
                <div className="mt-0.5 flex items-center gap-1.5">
                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--muted)]/40">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-blue-400 to-emerald-400 transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]/60">
                    {current}/{total}
                  </span>
                </div>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
