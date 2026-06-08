/**
 * teach-stream.ts — SSE stream consumer for /api/teach/continue/stream
 *
 * Fires callbacks as events arrive so the UI can render progressively:
 *   onThinking(content)  — "正在判题...", "查询教材..."
 *   onToolCall(tool, content)
 *   onToolResult(content)
 *   onContent(chunk)     — token-by-token teaching text
 *   onDone(result)       — final {evaluation, next_question, ...}
 *   onError(msg)
 */

export interface TeachStreamResult {
  reply: string;
  evaluation?: {
    is_correct: boolean;
    score: number;
    feedback: string;
    answer_key: string;
    explanation?: string;
    knowledge_point?: string;
  };
  next_question?: Record<string, unknown> | null;
  current?: number;
  total_questions?: number;
  correct_count?: number;
  wrong_count?: number;
  done?: boolean;
}

export async function fetchTeachStream(
  sessionId: string,
  message: string,
  callbacks: {
    onThinking?: (text: string) => void;
    onToolCall?: (tool: string, text: string) => void;
    onToolResult?: (text: string) => void;
    onContent?: (chunk: string) => void;
    onDone?: (result: TeachStreamResult) => void;
    onError?: (msg: string) => void;
  },
  signal?: AbortSignal,
): Promise<void> {
  const { onThinking, onToolCall, onToolResult, onContent, onDone, onError } = callbacks;

  try {
    const res = await fetch("/api/platform/teach/continue/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        teach_session_id: sessionId,
        message,
      }),
      signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      onError?.(`请求失败 (${res.status}): ${text}`);
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      onError?.("响应体不可读");
      return;
    }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Parse SSE events from buffer
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";  // keep last incomplete chunk

      for (const part of parts) {
        for (const line of part.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          try {
            const event = JSON.parse(line.slice(6));
            const type = event.type as string;
            const content = (event.content as string) ?? "";
            const meta = event.metadata as Record<string, unknown> ?? {};

            switch (type) {
              case "thinking":
                onThinking?.(content);
                break;
              case "tool_call":
                onToolCall?.((meta.tool as string) ?? "", content);
                break;
              case "tool_result":
                onToolResult?.(content);
                break;
              case "content":
                onContent?.(content);
                break;
              case "done":
                const result: TeachStreamResult = {
                  reply: (meta.reply as string) ?? "",
                  evaluation: meta.evaluation as TeachStreamResult["evaluation"],
                  next_question: meta.next_question as Record<string, unknown> | null,
                  current: meta.current as number,
                  total_questions: meta.total_questions as number,
                  correct_count: meta.correct_count as number,
                  wrong_count: meta.wrong_count as number,
                  done: meta.done as boolean,
                };
                onDone?.(result);
                break;
              case "error":
                onError?.(content);
                break;
            }
          } catch {
            // skip unparseable lines
          }
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") return;
    onError?.(err instanceof Error ? err.message : String(err));
  }
}
