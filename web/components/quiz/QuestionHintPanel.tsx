"use client";

import { useState, useCallback } from "react";
import { ChevronDown, ChevronUp, Lightbulb, GraduationCap, BookOpen } from "lucide-react";

interface QuestionHintPanelProps {
  hints: string[];
}

const HINT_LABELS = ["L1 概念引导", "L2 关键步骤", "L3 完整思路"];
const HINT_ICONS = [Lightbulb, GraduationCap, BookOpen];
const HINT_COLORS = [
  "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300",
  "border-orange-200 bg-orange-50 text-orange-800 dark:border-orange-800 dark:bg-orange-950/30 dark:text-orange-300",
  "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-300",
];

/** Progressive 3-level hint panel for guided teaching.
 *  L1→L2→L3 unlock sequentially; expanded hints stay visible. */
export default function QuestionHintPanel({ hints }: QuestionHintPanelProps) {
  // activeLevel: 0=none, 1=L1, 2=L2, 3=L3
  const [activeLevel, setActiveLevel] = useState(0);

  const handleActivate = useCallback(
    (level: number) => {
      // Only allow unlocking next level
      if (level <= activeLevel + 1) {
        setActiveLevel(level);
      }
    },
    [activeLevel],
  );

  if (!hints || hints.length === 0) return null;

  return (
    <div className="rounded-xl border border-[var(--border)]/60 bg-[var(--card)] p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <span className="text-[12px] font-medium text-[var(--muted-foreground)]">
          💡 需要提示吗？
        </span>
      </div>

      <div className="space-y-1.5">
        {hints.slice(0, 3).map((hint, i) => {
          const level = i + 1;
          const isUnlocked = level <= activeLevel;
          const canActivate = level === activeLevel + 1;
          const isNextToUnlock = level === activeLevel + 1 && activeLevel < 3;
          const Icon = HINT_ICONS[i];

          return (
            <div key={level}>
              <button
                type="button"
                disabled={!canActivate && !isUnlocked}
                onClick={() => canActivate && handleActivate(level)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[12px] font-medium transition-all ${
                  isUnlocked
                    ? HINT_COLORS[i] + " border"
                    : isNextToUnlock
                      ? "border border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--primary)]/30 cursor-pointer"
                      : "border border-[var(--border)]/30 bg-[var(--muted)]/30 text-[var(--muted-foreground)]/40 cursor-not-allowed"
                }`}
              >
                <Icon
                  size={14}
                  className={isUnlocked ? "" : "opacity-40"}
                />
                <span className="flex-1">{HINT_LABELS[i]}</span>
                {isUnlocked ? (
                  <ChevronUp size={14} />
                ) : isNextToUnlock ? (
                  <ChevronDown size={14} className="text-[var(--muted-foreground)]" />
                ) : (
                  <span className="text-[10px] opacity-40">🔒</span>
                )}
              </button>

              {isUnlocked && (
                <div className={`mt-1 rounded-lg border px-3 py-2 text-[12px] leading-relaxed ${HINT_COLORS[i]}`}>
                  {hint}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
