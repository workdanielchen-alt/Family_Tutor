"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAppShell } from "@/context/AppShellContext";
import { fetchMasterySummary } from "@/lib/platform-api";
import { Check, Loader2, Lock, Trophy } from "lucide-react";

const ACHIEVEMENT_LIST = [
  { id: "first_answer", name: "第一次答题", icon: "🎖️" },
  { id: "ten_answers", name: "答题数破10", icon: "🎖️" },
  { id: "fifty_answers", name: "答题数破50", icon: "🏅" },
  { id: "streak_3", name: "连续学习3天", icon: "🔥" },
  { id: "streak_7", name: "学习满一周", icon: "🔥" },
  { id: "weak_point_first", name: "首次攻克薄弱点", icon: "💪" },
  { id: "perfect_session", name: "全对的一天", icon: "🌟" },
  { id: "mastery_90", name: "掌握度突破90%", icon: "👑" },
  { id: "five_days_week", name: "每周学习5天", icon: "📅" },
];

export default function ChildMePage() {
  const router = useRouter();
  const { uiMode, setUiMode } = useAppShell();
  const [learnerId] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("learning-dashboard-learner-id") || "default";
    }
    return "default";
  });
  const [totalQuestions, setTotalQuestions] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (uiMode !== "child") router.replace("/chat");
  }, [uiMode, router]);

  useEffect(() => {
    fetchMasterySummary(learnerId)
      .then((s) => setTotalQuestions(s?.total_questions ?? 0))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [learnerId]);

  const handleSwitchToStandard = () => {
    if (window.confirm("切换到标准模式？标准模式功能更多，适合家长使用。")) {
      setUiMode("standard");
      router.push("/chat");
    }
  };

  if (uiMode !== "child") return null;

  return (
    <div className="space-y-5">
      {/* Avatar & name */}
      <div className="flex flex-col items-center gap-3 py-4">
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-[var(--primary)]/10 text-[40px]">
          🎒
        </div>
        <div className="text-center">
          <h1 className="text-[22px] font-bold text-[var(--foreground)]">我的学习</h1>
          {loading ? (
            <Loader2 className="mx-auto mt-2 animate-spin" size={16} />
          ) : (
            <p className="text-[13px] text-[var(--muted-foreground)]">
              共完成 {totalQuestions} 道题
            </p>
          )}
        </div>
      </div>

      {/* Achievements */}
      <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
        <h2 className="mb-3 flex items-center gap-2 text-[16px] font-semibold text-[var(--foreground)]">
          <Trophy size={18} className="text-amber-500" />
          成就
        </h2>
        <div className="grid grid-cols-3 gap-2">
          {ACHIEVEMENT_LIST.map((ach) => {
            // Simple heuristic based on total questions (backend integration coming later)
            const isUnlocked = ach.id === "first_answer" ? totalQuestions >= 1
              : ach.id === "ten_answers" ? totalQuestions >= 10
              : ach.id === "fifty_answers" ? totalQuestions >= 50
              : false;
            return (
              <div
                key={ach.id}
                className={`flex flex-col items-center gap-1 rounded-xl p-3 text-center ${
                  isUnlocked
                    ? "bg-[var(--muted)]/30"
                    : "bg-[var(--muted)]/10 opacity-50"
                }`}
              >
                <span className="text-[24px]">
                  {isUnlocked ? ach.icon : <Lock size={18} />}
                </span>
                <span className="text-[11px] font-medium text-[var(--foreground)]">
                  {ach.name}
                </span>
                {isUnlocked && (
                  <Check size={12} className="text-green-500" />
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Settings */}
      <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
        <h2 className="mb-3 text-[16px] font-semibold text-[var(--foreground)]">⚙️ 设置</h2>
        <button
          onClick={handleSwitchToStandard}
          className="w-full rounded-xl border border-[var(--border)] bg-[var(--muted)]/20 px-4 py-3 text-left text-[14px] text-[var(--foreground)] hover:bg-[var(--muted)]/40"
        >
          切换到标准模式
        </button>
      </section>
    </div>
  );
}
