"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";

import { useSettings } from "@/components/settings/SettingsContext";
import { useAppShell } from "@/context/AppShellContext";
import { ThemePreviewCard } from "@/components/settings/ThemePreviewCard";
import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
} from "@/components/settings/shared";

export default function AppearanceSettingsPage() {
  const { t } = useTranslation();
  const { theme, language, updateTheme, updateLanguage } = useSettings();
  const { uiMode } = useAppShell();

  return (
    <div data-tour="tour-appearance">
      <SettingsPageHeader
        title={t("Appearance")}
        description={t(
          "Tune the visual theme and interface language. Changes apply immediately and are stored in your account.",
        )}
      />

      <SettingSection
        title={t("Language")}
        description={t("Choose the interface language.")}
      >
        <SettingRow
          title={t("Interface language")}
          description={t(
            "Affects the UI only. Model output language is controlled by your prompt.",
          )}
          control={
            <div className="flex gap-0.5 rounded-lg bg-[var(--muted)] p-0.5">
              {(["en", "zh"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => updateLanguage(v)}
                  className={`rounded-md px-2.5 py-1 text-[12px] transition-all ${
                    language === v
                      ? "bg-[var(--card)] font-medium text-[var(--foreground)] shadow-sm"
                      : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  {v === "en" ? t("language.english") : t("language.chinese")}
                </button>
              ))}
            </div>
          }
        />
      </SettingSection>

      <SettingSection
        title={t("Theme")}
        description={t(
          "Pick the colour palette and interface style. Each tile previews the theme it applies.",
        )}
      >
        <div className="py-4">
          {/* Order is intentional: warm-light → cool-light → warm-dark →
              cool-dark. Cream is the default, Snow is its cool sibling,
              Dark mirrors Cream's accent, Glass mirrors Snow's. */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                { id: "light", label: t("Cream") },
                { id: "snow", label: t("Snow") },
                { id: "dark", label: t("Dark") },
                { id: "glass", label: t("Glass") },
              ] as const
            ).map(({ id, label }) => (
              <ThemePreviewCard
                key={id}
                theme={id}
                label={label}
                selected={theme === id}
                onSelect={updateTheme}
              />
            ))}
          </div>
          <p className="mt-4 text-[11.5px] leading-relaxed text-[var(--muted-foreground)]/80">
            {t(
              "Cream is a warm, paper-like default with a terracotta accent. Snow is its cool, blue-tinted sibling with a royal-blue accent. Dark keeps Cream's warmth on near-black. Glass adds translucent purple panels on a deep gradient.",
            )}
          </p>
        </div>
      </SettingSection>

      <SettingSection
        title="儿童模式"
        description="为孩子提供大字、大按钮、Emoji 激励的简化界面。"
      >
        <SettingRow
          title="开启儿童模式"
          description="适合 K9 学生独立使用。切换后首页变为学习大屏，底部 Tab Bar 替代侧边栏。"
          control={<ChildModeToggle />}
        />
        {uiMode === "child" && <ChildModeSettings />}
      </SettingSection>
    </div>
  );
}


function ChildModeToggle() {
  const { uiMode, setUiMode } = useAppShell();
  const router = useRouter();

  const handleToggle = () => {
    if (uiMode === "child") {
      setUiMode("standard");
    } else {
      setUiMode("child");
      router.push("/home");
    }
  };

  return (
    <button
      onClick={handleToggle}
      className={`relative inline-flex h-7 w-11 items-center rounded-full transition-colors ${
        uiMode === "child" ? "bg-[var(--primary)]" : "bg-[var(--muted)]"
      }`}
      role="switch"
      aria-checked={uiMode === "child"}
    >
      <span
        className={`inline-block h-5 w-5 rounded-full bg-white transition-transform ${
          uiMode === "child" ? "translate-x-[22px]" : "translate-x-[2px]"
        }`}
      />
    </button>
  );
}


function ChildModeSettings() {
  const [childName, setChildName] = useState(() => {
    if (typeof window !== "undefined") return localStorage.getItem("child-name") || "";
    return "";
  });
  const [dailyGoal, setDailyGoal] = useState(() => {
    if (typeof window !== "undefined") return localStorage.getItem("child-daily-goal") || "10";
    return "10";
  });
  const [subjects, setSubjects] = useState(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("child-subjects");
      return saved ? JSON.parse(saved) : ["math"];
    }
    return ["math"];
  });

  const updateName = (v: string) => {
    setChildName(v);
    localStorage.setItem("child-name", v);
  };
  const updateGoal = (v: string) => {
    setDailyGoal(v);
    localStorage.setItem("child-daily-goal", v);
  };
  const toggleSubject = (subj: string) => {
    const next = subjects.includes(subj) ? subjects.filter((s: string) => s !== subj) : [...subjects, subj];
    setSubjects(next);
    localStorage.setItem("child-subjects", JSON.stringify(next));
  };

  return (
    <div className="mt-4 space-y-3 border-t border-[var(--border)]/60 pt-4">
      <SettingRow
        title="👤 孩子姓名"
        description="首页问候语中使用的名字。"
        control={
          <input
            type="text"
            value={childName}
            onChange={(e) => updateName(e.target.value)}
            placeholder="小明"
            className="w-28 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[13px] text-[var(--foreground)] outline-none"
          />
        }
      />
      <SettingRow
        title="🎯 每日目标题数"
        description="达到后显示「今日目标已完成！」"
        control={
          <select
            value={dailyGoal}
            onChange={(e) => updateGoal(e.target.value)}
            className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1.5 text-[13px] text-[var(--foreground)] outline-none"
          >
            {[5, 10, 15, 20, 30].map((n) => (
              <option key={n} value={n}>{n} 题</option>
            ))}
          </select>
        }
      />
      <SettingRow
        title="📚 学习范围"
        description="选择孩子正在学习的科目。"
        control={
          <div className="flex gap-1.5">
            {[
              { id: "math", label: "数学" },
              { id: "physics", label: "物理" },
              { id: "chemistry", label: "化学" },
            ].map((s) => (
              <button
                key={s.id}
                onClick={() => toggleSubject(s.id)}
                className={`rounded-lg px-3 py-1.5 text-[12px] font-medium transition-colors ${
                  subjects.includes(s.id)
                    ? "bg-[var(--primary)] text-white"
                    : "border border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        }
      />
    </div>
  );
}
