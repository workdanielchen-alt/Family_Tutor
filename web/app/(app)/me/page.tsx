"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Loader2, Trophy, Flame, Zap, Award, Star, Target,
  CalendarCheck, CheckCircle2, TrendingUp, BookOpen,
  ChevronRight, Clock,
} from "lucide-react";
import {
  fetchMotivation, fetchMasterySummary, fetchWeeklyStats,
  type MotivationInfo, type MasterySummary, type PeriodStats,
} from "@/lib/platform-api";

const LEARNER_ID = "default";

// Achievement definitions matching backend
const ACHIEVEMENTS = [
  { id: "first_answer", name: "第一次答题", icon: Star, desc: "完成首次答题" },
  { id: "ten_answers", name: "答题数破10", icon: Target, desc: "累计答题超过10道" },
  { id: "fifty_answers", name: "答题数破50", icon: Award, desc: "累计答题超过50道" },
  { id: "streak_3", name: "连续学习3天", icon: Flame, desc: "连续3天学习" },
  { id: "streak_7", name: "学习满一周", icon: CalendarCheck, desc: "连续7天学习" },
  { id: "weak_point_first", name: "首次攻克薄弱点", icon: CheckCircle2, desc: "首次将薄弱知识点掌握度提升至60%以上" },
  { id: "perfect_session", name: "全对的一天", icon: Trophy, desc: "单日全部答对" },
  { id: "mastery_90", name: "掌握度突破90%", icon: Zap, desc: "某个知识点达到90%掌握度" },
  { id: "five_days_week", name: "每周学习5天", icon: TrendingUp, desc: "一周内学习5天以上" },
];

export default function MePage() {
  const [motiv, setMotiv] = useState<MotivationInfo | null>(null);
  const [summary, setSummary] = useState<MasterySummary | null>(null);
  const [weekly, setWeekly] = useState<PeriodStats | null>(null);
  const [loading, setLoading] = useState(true);

  // For simplicity, we don't have a "get achievements list" API.
  // We use achievement_count and show all, marking unlocked by count.
  const unlockedCount = motiv?.achievement_count ?? 0;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [m, s, w] = await Promise.all([
          fetchMotivation(LEARNER_ID),
          fetchMasterySummary(LEARNER_ID),
          fetchWeeklyStats(LEARNER_ID),
        ]);
        if (!cancelled) { setMotiv(m); setSummary(s); setWeekly(w); }
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  const level = motiv?.level ?? 1;
  const points = motiv?.points ?? 0;
  const currentLevelXp = (level - 1) * (level - 1) * 100;
  const nextLevelXp = level * level * 100;
  const levelProgress = Math.min(100, Math.round(((points - currentLevelXp) / (nextLevelXp - currentLevelXp)) * 100));

  return (
    <div className="space-y-5">
      {/* Profile card */}
      <div className="rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 p-5 text-white shadow-lg">
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-white/20 text-3xl">
            🎓
          </div>
          <div>
            <p className="text-lg font-bold">
              {(motiv?.streak_current ?? 0) > 0
                ? `坚持 ${motiv?.streak_current} 天 ✨`
                : "开始学习吧！"}
            </p>
            <p className="text-sm opacity-70">最长连续 {motiv?.streak_longest ?? 0} 天</p>
          </div>
        </div>

        {/* Level & XP */}
        <div className="mt-4 flex items-center gap-3">
          <div className="rounded-xl bg-white/15 px-3 py-2 text-center min-w-[60px]">
            <p className="text-2xl font-bold">{level}</p>
            <p className="text-[10px] opacity-70">等级</p>
          </div>
          <div className="flex-1">
            <div className="flex justify-between text-xs mb-1">
              <span>{points} XP</span>
              <span>{nextLevelXp} XP</span>
            </div>
            <div className="h-2.5 rounded-full bg-white/25">
              <div
                className="h-full rounded-full bg-white transition-all"
                style={{ width: `${levelProgress}%` }}
              />
            </div>
          </div>
          <div className="rounded-xl bg-white/15 px-3 py-2 text-center min-w-[60px]">
            <p className="text-2xl font-bold">{motiv?.streak_current ?? 0}</p>
            <p className="text-[10px] opacity-70">🔥 连续</p>
          </div>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl bg-[var(--card)] p-4 border border-[var(--border)]/50">
          <Trophy className="h-5 w-5 text-yellow-500 mb-1" />
          <p className="text-2xl font-bold text-[var(--foreground)]">{summary?.total_questions ?? 0}</p>
          <p className="text-xs text-[var(--muted-foreground)]">总答题数</p>
        </div>
        <div className="rounded-xl bg-[var(--card)] p-4 border border-[var(--border)]/50">
          <Target className="h-5 w-5 text-green-500 mb-1" />
          <p className="text-2xl font-bold text-[var(--foreground)]">
            {Math.round((summary?.accuracy ?? 0) * 100)}%
          </p>
          <p className="text-xs text-[var(--muted-foreground)]">总正确率</p>
        </div>
        <div className="rounded-xl bg-[var(--card)] p-4 border border-[var(--border)]/50">
          <BookOpen className="h-5 w-5 text-blue-500 mb-1" />
          <p className="text-2xl font-bold text-[var(--foreground)]">
            {summary?.mastered ?? 0}/{summary?.total_kp ?? 0}
          </p>
          <p className="text-xs text-[var(--muted-foreground)]">已掌握KP</p>
        </div>
        <div className="rounded-xl bg-[var(--card)] p-4 border border-[var(--border)]/50">
          <TrendingUp className="h-5 w-5 text-orange-500 mb-1" />
          <p className="text-2xl font-bold text-[var(--foreground)]">
            {Math.round((motiv?.weekly_accuracy ?? 0) * 100)}%
          </p>
          <p className="text-xs text-[var(--muted-foreground)]">本周正确率</p>
        </div>
      </div>

      {/* Quick links */}
      <div className="space-y-2">
        <Link
          href="/space"
          className="flex items-center gap-3 rounded-xl bg-[var(--card)] p-4 border border-[var(--border)]/50
            active:scale-[0.98] transition-transform"
        >
          <TrendingUp className="h-5 w-5 text-blue-500" />
          <span className="flex-1 text-sm text-[var(--foreground)]">学习进度详情</span>
          <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
        </Link>
        <Link
          href="/space/wrong-answers"
          className="flex items-center gap-3 rounded-xl bg-[var(--card)] p-4 border border-[var(--border)]/50
            active:scale-[0.98] transition-transform"
        >
          <Clock className="h-5 w-5 text-red-500" />
          <span className="flex-1 text-sm text-[var(--foreground)]">错题本</span>
          <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
        </Link>
      </div>

      {/* Achievements */}
      <div className="rounded-xl bg-[var(--card)] p-4 border border-[var(--border)]/50">
        <p className="mb-3 text-sm font-semibold text-[var(--muted-foreground)] flex items-center gap-2">
          <Award className="h-4 w-4" /> 成就 ({unlockedCount}/{ACHIEVEMENTS.length})
        </p>
        <div className="grid grid-cols-3 gap-3">
          {ACHIEVEMENTS.map((ach, i) => {
            const unlocked = i < unlockedCount;
            const Icon = ach.icon;
            return (
              <div
                key={ach.id}
                className={`rounded-xl p-3 text-center border transition-colors ${
                  unlocked
                    ? "border-yellow-300 bg-yellow-50 dark:bg-yellow-900/10"
                    : "border-[var(--border)]/50 bg-[var(--muted)]/20 opacity-50"
                }`}
              >
                <Icon className={`mx-auto h-6 w-6 ${unlocked ? "text-yellow-500" : "text-[var(--muted-foreground)]"}`} />
                <p className="mt-1 text-xs font-medium text-[var(--foreground)]">{ach.name}</p>
                <p className="text-[10px] text-[var(--muted-foreground)]">{ach.desc}</p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
