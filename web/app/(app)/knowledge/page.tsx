/**
 * Knowledge base page.
 */
import { Suspense } from "react";
import KnowledgePage from "@/components/knowledge/KnowledgePage";

export const dynamic = "force-dynamic";

export default function Page() {
  return (
    <Suspense fallback={null}>
      <KnowledgePage />
    </Suspense>
  );
}
