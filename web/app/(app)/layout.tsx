"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, BarChart3, PenLine, User } from "lucide-react";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import UtilitySidebar from "@/components/sidebar/UtilitySidebar";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";

const WORKSPACE_PATHS = ["/", "/chat", "/agents", "/book", "/playground"];
const CHILD_PATHS = ["/home", "/progress", "/practice", "/me"];

const CHILD_TABS = [
  { key: "home", href: "/home", icon: Home, label: "学习" },
  { key: "progress", href: "/progress", icon: BarChart3, label: "进度" },
  { key: "quiz", href: "/practice", icon: PenLine, label: "练习" },
  { key: "me", href: "/me", icon: User, label: "我的" },
];

function AppLayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isChild = CHILD_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));
  const isWorkspace = WORKSPACE_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));

  // Child mode: bottom tab bar
  if (isChild) {
    const activeTab = CHILD_TABS.find((t) => pathname.startsWith(t.href)) || CHILD_TABS[0];
    return (
      <div className="flex h-screen flex-col bg-[var(--background)]">
        <main className="flex-1 overflow-y-auto px-4 py-4 pb-20">
          <div className="mx-auto max-w-2xl">{children}</div>
        </main>
        <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-[var(--border)]/60 bg-[var(--card)] pb-[env(safe-area-inset-bottom)]">
          <div className="mx-auto flex max-w-lg items-center justify-around px-2 py-1">
            {CHILD_TABS.map((tab) => {
              const isActive = tab.key === activeTab.key;
              return (
                <Link
                  key={tab.key}
                  href={tab.href}
                  className={`flex flex-col items-center gap-0.5 rounded-xl px-5 py-2 transition-colors min-h-[52px] min-w-[64px] justify-center ${
                    isActive ? "text-[var(--primary)]" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                  }`}
                >
                  <tab.icon size={28} strokeWidth={isActive ? 2.5 : 1.8} />
                  <span className={`text-[14px] font-medium ${isActive ? "font-semibold" : ""}`}>{tab.label}</span>
                </Link>
              );
            })}
          </div>
        </nav>
      </div>
    );
  }

  // Standard mode: sidebar
  return (
    <div className="flex h-screen overflow-hidden">
      {isWorkspace ? <WorkspaceSidebar /> : <UtilitySidebar />}
      <main className="flex-1 overflow-hidden bg-[var(--background)]">
        {children}
      </main>
    </div>
  );
}

export default function AppLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <UnifiedChatProvider>
      <AppLayoutInner>{children}</AppLayoutInner>
    </UnifiedChatProvider>
  );
}
