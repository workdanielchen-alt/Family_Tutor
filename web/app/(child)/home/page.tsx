"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Home,
  BarChart3,
  PenLine,
  User,
  Loader2,
  AlertCircle,
  BookOpen,
  TrendingUp,
  Target,
  Sparkles,
  ChevronRight,
  Check,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useAppShell } from "@/context/AppShellContext";
import {
  fetchMasterySummary,
  fetchWeakPoints,
  fetchWeeklyStats,
  fetchMotivation,
  generatePractice,
  type MasterySummary,
  type WeakPoint,
  type MotivationInfo,
} from "@/lib/platform-api";

export default function ChildHomePage() {
  const router = useRouter();
  const { setUiMode } = useAppShell();

  const [learnerId] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("learning-dashboard-learner-id") || "default";
    }
    return "default";
  });

  const [summary, setSummary] = useState<MasterySummary | null>(null);
  const [weakPoints, setWeakPoints] = useState<WeakPoint[]>([]);
  const [weeklyStats, setWeeklyStats] = useState<{ total: number; accuracy: number } | null>(null);
  const [motivation, setMotivation] = useState<MotivationInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [greeting, setGreeting] = useState("你好");

  // ── Greeting based on time of day ──
  useEffect(() => {
    const hour = new Date().getHours();
    if (hour < 6) setGreeting("这么晚还没睡");
    else if (hour < 9) setGreeting("早上好");
    else if (hour < 12) setGreeting("上午好");
    else if (hour < 14) setGreeting("中午好");
    else if (hour < 18) setGreeting("下午好");
    else setGreeting("晚上好");
  }, []);

  // ── Load data ──
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sum, weak, weekly, mot] = await Promise.all([
        fetchMasterySummary(learnerId).catch(() => null),
        fetchWeakPoints(learnerId).catch(() => []),
        fetchWeeklyStats(learnerId).catch(() => null),
        fetchMotivation(learnerId).catch(() => null),
      ]);
      setSummary(sum);
      setWeakPoints(weak);
      setWeeklyStats(weekly);
      setMotivation(mot);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [learnerId]);

  useEffect(() => { loadData(); }, [loadData]);

  // ── Handle practice generation ──
  const handlePractice = useCallback(async (kpId: string) => {
    router.push(`/quiz?kpId=${encodeURIComponent(kpId)}`);
  }, [router]);

  const handleSwitchMode = useCallback(() => {
    setUiMode("standard");
    router.push("/chat");
  }, [router, setUiMode]);

  // ── Render ──

  if (loading && !summary) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin text-[var(--muted-foreground)]" size={28} />
        <span className="ml-3 text-[16px] text-[var(--muted-foreground)]">加载中...</span>
      </div>
    );
  }

  if (error && !summary) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-xl border border-red-200 bg-red-50 p-8 text-center">
        <AlertCircle className="text-red-500" size={32} />
        <p className="text-[15px] text-red-600">{error}</p>
        <button
          onClick={loadData}
          className="rounded-lg bg-red-500 px-5 py-2.5 text-[14px] text-white hover:bg-red-600"
        >
          重试
        </button>
      </div>
    );
  }

  const isEmpty = summary && summary.total_questions === 0;
  const weeklyAccuracy = weeklyStats?.accuracy != null ? Math.round(weeklyStats.accuracy * 100) : 0;
  const weakCount = weakPoints.length;
  const streakDays = motivation?.streak_current ?? 0;
  const level = motivation?.level ?? 1;
  const points = motivation?.points ?? 0;

  return (
    <div className="space-y-5">
      {/* ── Top streak bar ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--primary)]/10 text-[22px]">
            🎒
          </div>
          <div>
            <h1 className="text-[20px] font-bold text-[var(--foreground)]">
              {greeting}！
            </h1>
            <p className="text-[13px] text-[var(--muted-foreground)]">
              {streakDays > 0 ? `🔥 连续学习 ${streakDays} 天` : "今天也要加油哦！"}
            </p>
          </div>
        </div>
        <button
          onClick={handleSwitchMode}
          className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
          title="切换到标准模式"
        >
          {level > 1 ? `⭐ Lv.${level}` : "标准模式"}
        </button>
      </div>

      {isEmpty ? (
        <div className="flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed border-[var(--border)]/60 p-10 text-center">
          <BookOpen size={48} className="text-[var(--muted-foreground)]/40" />
          <p className="text-[17px] font-medium text-[var(--foreground)]">还没有学习记录</p>
          <p className="max-w-xs text-[14px] text-[var(--muted-foreground)]">
            通过微信发送作业照片，AI 老师会帮你逐题讲解！
          </p>
        </div>
      ) : (
        <>
          {/* ── Stat cards ── */}
          <div className="grid grid-cols-2 gap-3">
            <StatCardBig
              icon={Target}
              label="今日做题"
              value={summary?.total_questions ?? 0}
              unit="道"
              colorClass="bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400"
            />
            <StatCardBig
              icon={TrendingUp}
              label="本周正确率"
              value={weeklyAccuracy > 0 ? `${weeklyAccuracy}%` : "—"}
              unit=""
              colorClass="bg-green-50 text-green-600 dark:bg-green-950/30 dark:text-green-400"
            />
            <StatCardBig
              icon={Check}
              label="已掌握"
              value={summary?.mastered ?? 0}
              unit="个"
              colorClass="bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400"
            />
            <StatCardBig
              icon={AlertCircle}
              label="需要加强"
              value={weakCount}
              unit="个"
              colorClass="bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
            />
          </div>

          {/* ── Today's recommendation ── */}
          {weakPoints.length > 0 && (
            <section className="rounded-2xl border border-amber-200/60 bg-gradient-to-br from-amber-50 to-orange-50 p-4 shadow-sm dark:border-amber-800/30 dark:from-amber-950/20 dark:to-orange-950/20">
              <h2 className="flex items-center gap-2 text-[16px] font-semibold text-[var(--foreground)]">
                <Sparkles size={18} className="text-amber-500" />
                今日推荐
              </h2>
              <div className="mt-2 space-y-2">
                {weakPoints.slice(0, 2).map((wp) => (
                  <div key={wp.kp_id} className="flex items-center justify-between rounded-xl bg-white/60 p-3 dark:bg-black/20">
                    <div>
                      <p className="text-[15px] font-medium text-[var(--foreground)]">
                        📐 {wp.kp_id.split("/").pop()}
                      </p>
                      <p className="text-[12px] text-[var(--muted-foreground)]">
                        掌握度 {Math.round(wp.level * 100)}% · 答 {wp.total} 对 {wp.correct}
                      </p>
                    </div>
                    <button
                      onClick={() => handlePractice(wp.kp_id)}
                      className="flex items-center gap-1 rounded-xl bg-amber-500 px-5 py-2.5 text-[14px] font-bold text-white hover:bg-amber-600"
                    >
                      开始练习 🚀
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── Weak points (additional if more than 2) ── */}
          {weakPoints.length > 2 && (
            <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
              <h2 className="mb-3 flex items-center gap-2 text-[16px] font-semibold text-[var(--foreground)]">
                💪 需要巩固的知识点
              </h2>
              <div className="space-y-2">
                {weakPoints.slice(2, 6).map((wp) => (
                  <div key={wp.kp_id} className="flex items-center justify-between rounded-xl border border-[var(--border)]/60 bg-[var(--muted)]/20 p-3">
                    <div>
                      <p className="text-[15px] font-medium text-[var(--foreground)]">{wp.kp_id.split("/").pop()}</p>
                      <p className="text-[12px] text-[var(--muted-foreground)]">掌握度 {Math.round(wp.level * 100)}%</p>
                    </div>
                    <button onClick={() => handlePractice(wp.kp_id)} className="flex items-center gap-1 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-white hover:opacity-90">
                      练习 <ChevronRight size={15} />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── Three-tier mastery display ── */}
          {summary && summary.total_kp > 0 && (
            <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
              <h2 className="mb-3 flex items-center gap-2 text-[16px] font-semibold text-[var(--foreground)]">
                📊 我的知识点
              </h2>
              <div className="space-y-3">
                {/* Strong (已掌握) */}
                {summary.mastered > 0 && (
                  <div>
                    <p className="mb-1.5 text-[13px] font-medium text-green-600 dark:text-green-400">✅ 已掌握</p>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="rounded-full bg-green-100 px-3 py-1.5 text-[13px] text-green-700 dark:bg-green-900/30 dark:text-green-300">
                        共 {summary.mastered} 个知识点 ✓
                      </span>
                    </div>
                  </div>
                )}
                {/* Weak (需要加强) */}
                {weakPoints.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-[13px] font-medium text-amber-600 dark:text-amber-400">💪 需要加强</p>
                    <div className="flex flex-wrap gap-1.5">
                      {weakPoints.slice(0, 6).map((wp) => (
                        <span key={wp.kp_id} className="rounded-full bg-amber-100 px-3 py-1.5 text-[13px] text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                          {wp.kp_id.split("/").pop()}
                        </span>
                      ))}
                      {weakPoints.length > 6 && (
                        <span className="rounded-full bg-[var(--muted)] px-3 py-1.5 text-[13px] text-[var(--muted-foreground)]">
                          +{weakPoints.length - 6}
                        </span>
                      )}
                    </div>
                  </div>
                )}
                {/* Not yet learned */}
                <div>
                  <p className="mb-1.5 text-[13px] font-medium text-gray-500 dark:text-gray-400">🔴 还没学过</p>
                  <div className="flex flex-wrap gap-1.5">
                    <span className="rounded-full bg-gray-100 px-3 py-1.5 text-[13px] text-gray-500 dark:bg-gray-800 dark:text-gray-400">
                      继续学习，解锁更多知识点
                    </span>
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* ── Continue learning ── */}
          {summary && summary.total_questions > 0 && (
            <section className="rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm">
              <h2 className="mb-2 text-[16px] font-semibold text-[var(--foreground)]">
                📝 继续学习
              </h2>
              <p className="text-[14px] text-[var(--muted-foreground)]">
                上次做到第 {summary.total_questions} 题，要继续吗？
              </p>
              <button
                onClick={() => router.push("/progress")}
                className="mt-3 flex items-center gap-1.5 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-[14px] font-medium text-white hover:opacity-90"
              >
                继续做题
                <ChevronRight size={16} />
              </button>
            </section>
          )}
        </>
      )}

      {/* ── Quick tips ── */}
      <section className="rounded-2xl border border-[var(--border)]/60 bg-gradient-to-br from-[var(--card)] to-[var(--muted)]/20 p-4 text-center shadow-sm">
        <p className="text-[14px] leading-relaxed text-[var(--muted-foreground)]">
          💡 在微信里拍照发作业，AI 老师会逐题引导你完成！
        </p>
      </section>
    </div>
  );
}

// ── Big stat card for kids ──

function StatCardBig({
  icon: Icon,
  label,
  value,
  unit,
  colorClass,
}: {
  icon: any;
  label: string;
  value: string | number;
  unit: string;
  colorClass: string;
}) {
  return (
    <div className={`flex items-center gap-3 rounded-2xl border border-[var(--border)]/60 bg-[var(--card)] p-4 shadow-sm`}>
      <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${colorClass}`}>
        <Icon size={22} strokeWidth={1.8} />
      </span>
      <div>
        <p className="text-[12px] text-[var(--muted-foreground)]">{label}</p>
        <p className="text-[22px] font-bold tracking-tight text-[var(--foreground)]">
          {value}
          {unit && <span className="ml-0.5 text-[14px] font-normal text-[var(--muted-foreground)]">{unit}</span>}
        </p>
      </div>
    </div>
  );
}
