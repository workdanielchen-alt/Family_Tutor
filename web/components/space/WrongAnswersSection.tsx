"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Loader2,
  Play,
  Search,
} from "lucide-react";
import SpaceSectionHeader from "@/components/space/SpaceSectionHeader";
import {
  fetchWrongAnswers,
  generatePractice,
  type WrongAnswer,
} from "@/lib/platform-api";

const LEARNER_ID = "default";

interface GroupedWrong {
  kp_id: string;
  kp_name: string;
  items: WrongAnswer[];
}

export default function WrongAnswersSection() {
  const { t } = useTranslation();
  const [wrongAnswers, setWrongAnswers] = useState<WrongAnswer[]>([]);
  const [grouped, setGrouped] = useState<GroupedWrong[]>([]);
  const [expandedKp, setExpandedKp] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchWrongAnswers(LEARNER_ID, "", 50);
        if (!cancelled) {
          setWrongAnswers(data);
          const groups: Record<string, WrongAnswer[]> = {};
          for (const wa of data) {
            const kpId = wa.kp_id || "unknown";
            if (!groups[kpId]) groups[kpId] = [];
            groups[kpId].push(wa);
          }
          const g: GroupedWrong[] = Object.entries(groups).map(([kpId, items]) => ({
            kp_id: kpId,
            kp_name: kpId.split("/").pop() || kpId,
            items,
          }));
          g.sort((a, b) => b.items.length - a.items.length);
          setGrouped(g);
        }
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handlePractice = async (kpId: string) => {
    try {
      await generatePractice(LEARNER_ID, kpId, 5);
      alert(t("Practice generated! Go to Practice → Weak Point Practice to view."));
    } catch {
      alert(t("Generation failed. Please try again later."));
    }
  };

  const filtered = filter
    ? grouped.filter((g) => g.kp_name.toLowerCase().includes(filter.toLowerCase()))
    : grouped;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  return (
    <>
      <SpaceSectionHeader
        icon={AlertCircle}
        title={t("Wrong Answers")}
        description={t("Review mistakes grouped by knowledge point with practice generation.")}
        meta={
          <span className="rounded-md bg-[var(--muted)]/60 px-2 py-0.5 text-xs text-[var(--muted-foreground)]">
            {wrongAnswers.length} {t("questions")}
          </span>
        }
      />

      {/* Search */}
      {grouped.length > 5 && (
        <div className="relative mb-4">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-[var(--muted-foreground)]" />
          <input
            type="text"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("Search knowledge points...")}
            className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] py-2 pl-9 pr-3 text-sm
              placeholder:text-[var(--muted-foreground)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30"
          />
        </div>
      )}

      {/* Empty state */}
      {grouped.length === 0 && (
        <div className="rounded-xl bg-[var(--card)] p-8 text-center border border-[var(--border)]/50">
          <p className="text-lg text-[var(--muted-foreground)]">{t("No wrong answers yet!")}</p>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">{t("Keep up the good work!")}</p>
        </div>
      )}

      {/* Grouped list */}
      <div className="space-y-2">
        {filtered.map((g) => (
          <div
            key={g.kp_id}
            className="rounded-xl bg-[var(--card)] border border-[var(--border)]/50 overflow-hidden"
          >
            {/* Group header */}
            <button
              onClick={() => setExpandedKp(expandedKp === g.kp_id ? null : g.kp_id)}
              className="w-full flex items-center gap-3 p-3 text-left hover:bg-[var(--muted)]/30 transition-colors"
            >
              {expandedKp === g.kp_id ? (
                <ChevronUp className="h-4 w-4 text-[var(--muted-foreground)] shrink-0" />
              ) : (
                <ChevronDown className="h-4 w-4 text-[var(--muted-foreground)] shrink-0" />
              )}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-[var(--foreground)] truncate">
                  {g.kp_name}
                </p>
                <p className="text-xs text-[var(--muted-foreground)]">
                  {g.items.length} {t("wrong questions")}
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handlePractice(g.kp_id);
                }}
                className="flex items-center gap-1 rounded-lg bg-[var(--primary)]/10 px-3 py-1.5
                  text-xs font-medium text-[var(--primary)] hover:bg-[var(--primary)]/20"
              >
                <Play className="h-3 w-3" /> {t("Practice")}
              </button>
            </button>

            {/* Expanded items */}
            {expandedKp === g.kp_id && (
              <div className="border-t border-[var(--border)]/50 divide-y divide-[var(--border)]/30">
                {g.items.map((item, idx) => (
                  <div key={idx} className="p-3 space-y-2 text-sm">
                    <p className="font-medium text-[var(--foreground)]">
                      {idx + 1}. {item.question}
                    </p>
                    {item.user_answer && (
                      <div className="flex items-start gap-2">
                        <span className="text-[var(--muted-foreground)] shrink-0">
                          {t("Your answer")}:
                        </span>
                        <span className="text-red-500 line-through">
                          {item.user_answer}
                        </span>
                      </div>
                    )}
                    {item.correct_answer && (
                      <div className="flex items-start gap-2">
                        <span className="text-[var(--muted-foreground)] shrink-0">
                          {t("Correct answer")}:
                        </span>
                        <span className="text-green-600 font-medium">
                          {item.correct_answer}
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
