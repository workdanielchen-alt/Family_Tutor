"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import UtilitySidebar from "@/components/sidebar/UtilitySidebar";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";
import { useAppShell } from "@/context/AppShellContext";

const WORKSPACE_PATHS = ["/", "/chat", "/agents", "/book", "/playground"];

function AppLayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { uiMode } = useAppShell();
  const isWorkspace = WORKSPACE_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));

  // Redirect to child home when in child mode
  useEffect(() => {
    if (uiMode === "child") {
      router.replace("/home");
    }
  }, [uiMode, router]);

  if (uiMode === "child") return null;

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
