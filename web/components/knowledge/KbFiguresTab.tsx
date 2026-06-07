"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Image as ImageIcon, Loader2, Search } from "lucide-react";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";

// 走 proxy 路径（deeptutor:3782 → proxy 把 /api/platform/xxx → platform:8100/api/xxx）
const FIGURES_API = "/api/platform/kb/figures";

interface FigureResult {
  figure_id: string;
  fig_type: string;
  caption: string;
  source_file: string;
  page_num: number;
  description: string;
  score: number;
  image_url: string;
}

interface KbFiguresTabProps {
  kb: KnowledgeBase;
}

export default function KbFiguresTab({ kb }: KbFiguresTabProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<FigureResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const searchFigures = useCallback(
    async (q: string) => {
      if (!q.trim()) {
        setResults([]);
        return;
      }
      setLoading(true);
      try {
        const res = await fetch(
          `${FIGURES_API}/search?kb_name=${encodeURIComponent(
            kb.name,
          )}&query=${encodeURIComponent(q)}&top_k=50`,
        );
        const data = await res.json();
        if (data?.ok) {
          setResults(data.results ?? []);
        }
        setLoadedOnce(true);
      } catch {
        // Platform not reachable or no figures collection
        setResults([]);
        setLoadedOnce(true);
      } finally {
        setLoading(false);
      }
    },
    [kb.name],
  );

  // Auto-load on mount with broad search to show figures
  useEffect(() => {
    searchFigures("Figure");
  }, [searchFigures]);

  const handleInputChange = useCallback(
    (val: string) => {
      setQuery(val);
      if (searchTimer.current) clearTimeout(searchTimer.current);
      searchTimer.current = setTimeout(
        () => searchFigures(val || "Figure"),
        400,
      );
    },
    [searchFigures],
  );

  const figTypeLabel = (type: string) => {
    const map: Record<string, string> = {
      geometry: t("几何图"),
      function_graph: t("函数图"),
      table: t("表格"),
      illustration: t("插图"),
      unknown: t("图形"),
    };
    return map[type] || type;
  };

  return (
    <div className="flex h-full flex-col gap-4">
      {/* Search bar */}
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
        <input
          type="text"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          placeholder={t("搜索图形（留空显示全部）...")}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] py-2 pl-9 pr-3 text-[13px] outline-none transition-colors focus:border-[var(--primary)]"
        />
      </div>

      {/* Results */}
      {loading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
        </div>
      ) : results.length === 0 && loadedOnce ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-[var(--muted-foreground)]">
          <ImageIcon className="h-8 w-8 opacity-30" />
          <p className="text-[13px]">
            {t("该知识库暂无入库的图形")}
          </p>
          <p className="text-[11px]">
            {t("上传含图的 PDF 或图片文件后，图形将自动入库")}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 overflow-y-auto lg:grid-cols-3">
          {results.map((fig) => (
            <div
              key={fig.figure_id}
              className="group overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] transition-shadow hover:shadow-md"
            >
              {/* Image */}
              <div className="relative flex aspect-[4/3] items-center justify-center bg-[var(--muted)]/30 p-2">
                {fig.image_url ? (
                  <img
                    src={`/api/platform/kb/figures/${fig.figure_id}/image?kb_name=${encodeURIComponent(kb.name)}`}
                    alt={fig.caption || fig.description || "Figure"}
                    className="max-h-full max-w-full object-contain"
                    loading="lazy"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none";
                      (
                        e.target as HTMLImageElement
                      ).nextElementSibling?.classList.remove("hidden");
                    }}
                  />
                ) : null}
                <div className="hidden text-xs text-[var(--muted-foreground)]">
                  {t("图片不可用")}
                </div>
              </div>

              {/* Meta */}
              <div className="space-y-1 px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className="rounded-full bg-[var(--primary)]/10 px-2 py-0.5 text-[10px] font-medium text-[var(--primary)]">
                    {figTypeLabel(fig.fig_type)}
                  </span>
                  {fig.score > 0 && (
                    <span className="text-[10px] text-[var(--muted-foreground)]">
                      {Math.round(fig.score * 100)}%
                    </span>
                  )}
                </div>
                {fig.caption && (
                  <p className="truncate text-[11px] font-medium text-[var(--foreground)]">
                    {fig.caption}
                  </p>
                )}
                {fig.description && (
                  <p className="line-clamp-2 text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
                    {fig.description}
                  </p>
                )}
                {fig.source_file && (
                  <p className="truncate text-[9px] text-[var(--muted-foreground)] opacity-60">
                    {fig.source_file.split("/").pop()}
                    {fig.page_num > 0 ? ` · p.${fig.page_num + 1}` : ""}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
