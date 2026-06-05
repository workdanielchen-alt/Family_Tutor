"use client";

import { useState } from "react";
import { X, FileText, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

interface TaskCreateModalProps {
  /** Pre-filled title derived from filename */
  initialTitle: string;
  /** Original filename for display */
  filename: string;
  /** File size in bytes for display */
  fileSize?: number;
  /** Called when user confirms, passing the title */
  onConfirm: (title: string) => void | Promise<void>;
  /** Called when user cancels */
  onCancel: () => void;
  /** Whether the task is being created (loading state) */
  loading?: boolean;
  /** Error message to display when task creation fails */
  error?: string | null;
}

function formatSize(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function TaskCreateModal({
  initialTitle,
  filename,
  fileSize,
  onConfirm,
  onCancel,
  loading = false,
  error = null,
}: TaskCreateModalProps) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(initialTitle);

  const handleConfirm = () => {
    const trimmed = title.trim();
    if (!trimmed) return;
    void onConfirm(trimmed);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="mx-4 w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="mb-5 flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--primary)]/10">
              <FileText size={20} className="text-[var(--primary)]" />
            </div>
            <div>
              <h2 className="text-[15px] font-semibold text-[var(--foreground)]">
                新建任务会话
              </h2>
              <p className="text-[12px] text-[var(--muted-foreground)]">
                AI 老师将引导你逐题作答
              </p>
            </div>
          </div>
          <button
            onClick={onCancel}
            disabled={loading}
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/30 hover:text-[var(--foreground)]"
            aria-label={t("Cancel")}
          >
            <X size={16} />
          </button>
        </div>

        {/* File info */}
        <div className="mb-4 flex items-center gap-2 rounded-lg bg-[var(--muted)]/30 px-3 py-2">
          <span className="shrink-0 text-[14px]">📄</span>
          <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--foreground)]/80">
            {filename}
          </span>
          {fileSize ? (
            <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
              {formatSize(fileSize)}
            </span>
          ) : null}
        </div>

        {/* Title input */}
        <div className="mb-5">
          <label className="mb-1.5 block text-[12px] font-medium text-[var(--muted-foreground)]">
            会话标题
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleConfirm();
              if (e.key === "Escape") onCancel();
            }}
            autoFocus
            maxLength={60}
            placeholder="输入试卷名称"
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-[14px] text-[var(--foreground)] outline-none transition-colors placeholder:text-[var(--muted-foreground)]/50 focus:border-[var(--primary)]/40 focus:ring-1 focus:ring-[var(--primary)]/20"
          />
          <p className="mt-1 text-[11px] text-[var(--muted-foreground)]/60">
            {title.length}/60
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-300">
            <span className="mt-0.5 shrink-0">⚠️</span>
            <span className="flex-1">{error}</span>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2.5">
          <button
            onClick={onCancel}
            disabled={loading}
            className="flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2.5 text-[13px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/30 disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={handleConfirm}
            disabled={!title.trim() || loading}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2.5 text-[13px] font-medium text-white transition-colors hover:bg-[var(--primary)]/90 disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                创建中...
              </>
            ) : (
              "开始答题"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
