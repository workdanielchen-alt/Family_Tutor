/**
 * Knowledge base page.
 */
import { Suspense } from "react";
import { Loader2 } from "lucide-react";
import KnowledgePage from "@/components/knowledge/KnowledgePage";

export const dynamic = "force-dynamic";

function LoadingFallback() {
  return (
    <div className="flex h-full items-center justify-center bg-[var(--background)]">
      <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <KnowledgePage />
    </Suspense>
  );
}
