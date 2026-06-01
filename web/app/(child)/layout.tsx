"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { Home, BarChart3, PenLine, User } from "lucide-react";
import { useAppShell } from "@/context/AppShellContext";

const TABS = [
  { key: "home", href: "/home", icon: Home, label: "学习" },
  { key: "progress", href: "/progress", icon: BarChart3, label: "进度" },
  { key: "quiz", href: "/quiz", icon: PenLine, label: "练习" },
  { key: "me", href: "/me", icon: User, label: "我的" },
];

export default function ChildLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { uiMode } = useAppShell();

  // Redirect to standard mode if not in child mode
  useEffect(() => {
    if (uiMode !== "child") {
      router.replace("/chat");
    }
  }, [uiMode, router]);

  if (uiMode !== "child") return null;

  const activeTab = TABS.find((t) => pathname.startsWith(t.href)) || TABS[0];

  return (
    <div className="flex h-screen flex-col bg-[var(--background)]">
      {/* Main content area */}
      <main className="flex-1 overflow-y-auto px-4 py-4 pb-20">
        <div className="mx-auto max-w-2xl">{children}</div>
      </main>

      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--border)]/60 bg-[var(--card)] pb-[env(safe-area-inset-bottom)]">
        <div className="mx-auto flex max-w-lg items-center justify-around px-2 py-1">
          {TABS.map((tab) => {
            const isActive = tab.key === activeTab.key;
            return (
              <Link
                key={tab.key}
                href={tab.href}
                className={`flex flex-col items-center gap-0.5 rounded-xl px-5 py-2 transition-colors min-h-[52px] min-w-[64px] justify-center ${
                  isActive
                    ? "text-[var(--primary)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                <tab.icon
                  size={28}
                  strokeWidth={isActive ? 2.5 : 1.8}
                />
                <span className={`text-[14px] font-medium ${
                  isActive ? "font-semibold" : ""
                }`}>
                  {tab.label}
                </span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
