"use client";

/**
 * 已废弃 — 统一到会话模式。重定向回聊天页。
 * 原独立试卷答题页，现所有任务通过 TeachSession + 会话列表完成。
 */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function ChatQuizPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/chat");
  }, [router]);
  return null;
}
