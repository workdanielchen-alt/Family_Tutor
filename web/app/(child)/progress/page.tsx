"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAppShell } from "@/context/AppShellContext";
import { fetchWeeklyStats, fetchMonthlyStats, fetchMotivation, fetchWeakPoints, fetchMasterySummary, type MotivationInfo, type WeakPoint } from "@/lib/platform-api";
import { Loader2, TrendingUp, CalendarDays, ChevronRight } from "lucide-react";

export default function ChildProgressPage() {
  const router = useRouter();
  const { uiMode } = useAppShell();

  const [learnerId] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("learning-dashboard-learner-id") || "default";
    }
    return "default";
  });

  const [weeklyStats, setWeeklyStats] = useState<{ per_day: { date: string; total: number }[]; total: number; accuracy: number } | null>(null);
  const [motivation, setMotivation] = useState<MotivationInfo | null>(null);
  const [weakPoints, setWeakPoints] = useState<WeakPoint[]>([]);
  const [masteredCount, setMasteredCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (uiMode !== "child") router.replace("/chat");
  }, [uiMode, router]);

  const loadData = useCallback(async () => {
    try {
      const [weekly, mot, weak, mastery] = await Promise.all([
        fetchWeeklyStats(learnerId).catch(() => null),
        fetchMotivation(learnerId).catch(() => null),
        fetchWeakPoints(learnerId).catch(() => [] as WeakPoint[]),
        fetchMasterySummary(learnerId).catch(() => null),
      ]);
      setWeeklyStats(weekly);
      setMotivation(mot);
      setWeakPoints(weak);
      setMasteredCount(mastery?.mastered ?? 0);
    } catch { /* ignore */ }
    setLoading(false);
  }, [learnerId]);

  useEffect(() => { loadData(); }, [loadData]);

  if (uiMode !== "child") return null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin" size={28} />
        <span className="ml-3 text-[16px] text-[var(--muted-foreground)]">加载中...</span>
      </div>
    );
  }

  const days = weeklyStats?.per_day ?? [];
  const maxCount = Math.max(1, ...days.map(d => d.total));
  const weekdays = ["一", "二", "三", "四", "五", "六", "日"];

  return (
    <div className="space-y-5">
      <h1 className="text-[20px] font-bold text-[var(--foreground)]">📊 学习进度</h1>

      {/* Weekly bar chart */}
      <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
        <div className="mb-3 flex items-center gap-2">
          <TrendingUp size={18} className="text-[var(--primary)]" />
          <h2 className="text-[16px] font-semibold text-[var(--foreground)]">本周学习</h2>
          {weeklyStats && (
            <span className="ml-auto text-[13px] text-[var(--muted-foreground)]">
              共 {weeklyStats.total} 题 · 正确率 {Math.round(weeklyStats.accuracy * 100)}%
            </span>
          )}
        </div>

        {days.length === 0 ? (
          <p className="py-6 text-center text-[14px] text-[var(--muted-foreground)]">本周暂无学习记录</p>
        ) : (
          <div className="flex items-end justify-around gap-2 pt-2">
            {days.map((d, i) => {
              const pct = (d.total / maxCount) * 100;
              return (
                <div key={d.date} className="flex flex-col items-center gap-1.5">
                  <span className="text-[12px] font-medium text-[var(--muted-foreground)]">{d.total}</span>
                  <div className="relative h-20 w-8 rounded-lg bg-[var(--muted)]/50">
                    <div
                      className="absolute bottom-0 w-full rounded-lg bg-[var(--primary)]/70 transition-all"
                      style={{ height: `${Math.max(pct, d.total > 0 ? 8 : 0)}%`, minHeight: d.total > 0 ? "8px" : "0px" }}
                    />
                  </div>
                  <span className="text-[11px] text-[var(--muted-foreground)]">{weekdays[i] || ""}</span>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Streak & motivation */}
      {motivation && (
        <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
          <div className="flex items-center gap-2">
            <CalendarDays size={18} className="text-amber-500" />
            <h2 className="text-[16px] font-semibold text-[var(--foreground)]">学习记录</h2>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-amber-50 p-3 text-center dark:bg-amber-950/20">
              <p className="text-[24px] font-bold text-amber-600 dark:text-amber-400">{motivation.streak_current}</p>
              <p className="text-[12px] text-amber-700 dark:text-amber-300">连续学习（天）</p>
            </div>
            <div className="rounded-xl bg-blue-50 p-3 text-center dark:bg-blue-950/20">
              <p className="text-[24px] font-bold text-blue-600 dark:text-blue-400">{motivation.level}</p>
              <p className="text-[12px] text-blue-700 dark:text-blue-300">学习等级</p>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-green-50 p-3 text-center dark:bg-green-950/20">
              <p className="text-[24px] font-bold text-green-600 dark:text-green-400">{motivation.points}</p>
              <p className="text-[12px] text-green-700 dark:text-green-300">积分</p>
            </div>
            <div className="rounded-xl bg-purple-50 p-3 text-center dark:bg-purple-950/20">
              <p className="text-[24px] font-bold text-purple-600 dark:text-purple-400">{motivation.achievement_count}</p>
              <p className="text-[12px] text-purple-700 dark:text-purple-300">成就</p>
            </div>
          </div>
          {motivation.last_week_accuracy > 0 && motivation.weekly_accuracy > 0 && (
            <p className={`mt-3 text-center text-[13px] ${
              motivation.weekly_accuracy > motivation.last_week_accuracy
                ? "text-green-600 dark:text-green-400"
                : "text-[var(--muted-foreground)]"
            }`}>
              {motivation.weekly_accuracy > motivation.last_week_accuracy
                ? `↑ 比上周进步 ${Math.round(motivation.weekly_accuracy - motivation.last_week_accuracy)}%`
                : `本周正确率 ${Math.round(motivation.weekly_accuracy)}%`}
            </p>
          )}
        </section>
      )}

      {/* KP tags */}
      <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
        <h2 className="mb-3 text-[16px] font-semibold text-[var(--foreground)]">📊 知识点概览</h2>
        <div className="space-y-3">
          {masteredCount > 0 && (
            <div>
              <p className="mb-1.5 text-[13px] font-medium text-green-600 dark:text-green-400">✅ 掌握的知识点</p>
              <p className="text-[13px] text-[var(--muted-foreground)]">
                共 {masteredCount} 个知识点已掌握，继续加油！
              </p>
            </div>
          )}
          {weakPoints.length > 0 && (
            <div>
              <p className="mb-1.5 text-[13px] font-medium text-amber-600 dark:text-amber-400">💪 需要加强的知识点</p>
              <div className="flex flex-wrap gap-1.5">
                {weakPoints.slice(0, 6).map((wp) => (
                  <span key={wp.kp_id} className="rounded-full bg-amber-100 px-2.5 py-1 text-[12px] text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                    {wp.kp_id.split("/").pop()}
                  </span>
                ))}
              </div>
              <button
                onClick={() => router.push(`/quiz?kpId=${weakPoints[0].kp_id}`)}
                className="mt-2 flex items-center gap-1 text-[13px] font-medium text-[var(--primary)]"
              >
                去练习 ✏️ <ChevronRight size={14} />
              </button>
            </div>
          )}
        </div>
      </section>

      {/* Learning history */}
      <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
        <h2 className="mb-3 flex items-center gap-2 text-[16px] font-semibold text-[var(--foreground)]">
          📖 最近学过的
        </h2>
        {weakPoints.length > 0 ? (
          <ul className="space-y-1.5">
            {weakPoints.slice(0, 4).map((wp) => (
              <li key={wp.kp_id} className="flex items-center gap-2 text-[14px] text-[var(--muted-foreground)]">
                <span className="text-[var(--primary)]">·</span>
                {wp.kp_id.split("/").slice(0, 2).join(" · ")}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[14px] text-[var(--muted-foreground)]">还没有学习记录</p>
        )}
      </section>
    </div>
  );
}
