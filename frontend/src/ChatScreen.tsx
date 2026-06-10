import { useEffect, useMemo, useRef } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import type { ChatTransport, UIMessage as AiUIMessage } from "ai";
import { AlertCircle } from "lucide-react";
import { Message, Composer } from "@adambossy/agent-ui";
import type { UIMessage } from "@adambossy/agent-ui";

const MODEL = "gemini-3.5-flash";

// Reshape the AI SDK send body to the `{ id, message, selectedChatModel,
// selectedVisibilityType }` shape the backend's /api/chat expects.
function makeTransport(): ChatTransport<AiUIMessage> {
  return new DefaultChatTransport<AiUIMessage>({
    api: "/api/chat",
    prepareSendMessagesRequest: ({ id, messages }) => {
      const latest = messages[messages.length - 1];
      return {
        body: {
          id,
          message: { id: latest.id, role: "user", parts: latest.parts },
          selectedChatModel: MODEL,
          selectedVisibilityType: "private",
        },
      };
    },
  });
}

/** Extract a human-readable string from any AI SDK `error` state. */
function errorMessage(error: unknown): string {
  if (!error) return "";
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

/** Pull a stream-level `error` SSE frame out of the latest assistant message,
 * if the AI SDK didn't already surface it via the top-level `error` state. */
function findStreamError(messages: AiUIMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role !== "assistant") continue;
    const parts = (msg.parts ?? []) as Array<{ type?: string; errorText?: string; text?: string }>;
    for (const part of parts) {
      if (part?.type === "error" && typeof part.errorText === "string") return part.errorText;
    }
  }
  return null;
}

export function ChatScreen() {
  const sessionId = useMemo(() => crypto.randomUUID(), []);
  const transport = useMemo(() => makeTransport(), []);

  const { messages, sendMessage, status, error } = useChat({
    id: sessionId,
    transport,
    generateId: () => crypto.randomUUID(),
  });

  const transcriptRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status, error]);

  const isStreaming = status === "streaming" || status === "submitted";
  const showEmpty = messages.length === 0;

  // Top-level errors come from two paths:
  //   1. `useChat` exposes `error` for transport / parse failures.
  //   2. Stream-level `{type: "error", errorText}` frames are appended as a
  //      part on the assistant message — surface those too.
  const surfacedError = errorMessage(error) || findStreamError(messages as AiUIMessage[]);

  return (
    <div className="flex h-full w-full flex-col bg-background text-foreground">
      <div ref={transcriptRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-3 pt-4 pb-2 sm:px-4">
          {showEmpty ? (
            <div className="flex h-[70vh] flex-col items-center justify-center text-center">
              <h1 className="text-2xl font-semibold sm:text-3xl">What can I help with?</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Ask me anything — try <em>"What's the weather in San Francisco?"</em>
              </p>
            </div>
          ) : (
            messages.map((m, i) => (
              <Message
                key={m.id ?? i}
                message={m as unknown as UIMessage}
                isStreaming={isStreaming && i === messages.length - 1}
              />
            ))
          )}
          {surfacedError && (
            <div
              role="alert"
              className="mt-3 flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <div className="min-w-0 flex-1 whitespace-pre-wrap break-words">
                <strong className="font-medium">Error.</strong> {surfacedError}
              </div>
            </div>
          )}
        </div>
      </div>

      <Composer
        disabled={isStreaming}
        onSend={(text) => sendMessage({ text })}
        modelLabel="Gemini 3.5 Flash"
        footerHint="Connected to agent-harness"
      />
    </div>
  );
}
