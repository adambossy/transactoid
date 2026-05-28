import { useEffect, useMemo, useRef } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import type { ChatTransport, UIMessage as AiUIMessage } from "ai";
import { Message, Composer } from "@adambossy/agent-ui";
import type { UIMessage } from "@adambossy/agent-ui";

const MODEL = "gpt-5.5";

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

export function ChatScreen() {
  const sessionId = useMemo(() => crypto.randomUUID(), []);
  const transport = useMemo(() => makeTransport(), []);

  const { messages, sendMessage, status } = useChat({
    id: sessionId,
    transport,
    generateId: () => crypto.randomUUID(),
  });

  const transcriptRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status]);

  const isStreaming = status === "streaming" || status === "submitted";
  const showEmpty = messages.length === 0;

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
        </div>
      </div>

      <Composer
        disabled={isStreaming}
        onSend={(text) => sendMessage({ text })}
        modelLabel="GPT-5.5"
        footerHint="Connected to agent-harness"
      />
    </div>
  );
}
