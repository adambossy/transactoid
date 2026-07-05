import { useEffect, useMemo, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import type { ChatTransport, UIMessage as AiUIMessage } from "ai";
import { AlertCircle, Brain, SquarePen } from "lucide-react";
import { Message, Composer } from "@adambossy/agent-ui";
import type { UIMessage } from "@adambossy/agent-ui";
import { authHeaders, setAuthTokenGetter } from "./authFetch";

const MODEL = "gemini-3.5-flash";
const SESSION_KEY = "penny:sessionId";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;
type SessionMode = "individual" | "joint";

function loadOrCreateSessionId(): string {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const fresh = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, fresh);
  return fresh;
}

// Reshape the AI SDK send body to the shape the backend's /api/chat expects,
// attaching a fresh bearer token per request and the (creation-only) session
// mode. The backend ignores sessionMode on an existing conversation.
function makeTransport(
  getToken: GetToken,
  getSessionMode: () => SessionMode,
): ChatTransport<AiUIMessage> {
  return new DefaultChatTransport<AiUIMessage>({
    api: "/api/chat",
    prepareSendMessagesRequest: async ({ id, messages }) => {
      const latest = messages[messages.length - 1];
      return {
        headers: await authHeaders(getToken),
        body: {
          id,
          message: { id: latest.id, role: "user", parts: latest.parts },
          sessionMode: getSessionMode(),
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

/** True once the assistant message has anything the transcript can render —
 * the pending indicator yields to the real reasoning/text/tool parts. */
function hasVisibleParts(message: AiUIMessage): boolean {
  const parts = (message.parts ?? []) as Array<{ type?: string }>;
  return parts.some(
    (part) =>
      part?.type === "text" ||
      part?.type === "reasoning" ||
      part?.type === "dynamic-tool" ||
      (part?.type ?? "").startsWith("tool-"),
  );
}

/** Placeholder shown between message send and the first streamed part, so the
 * agent never looks unresponsive. Styled to match agent-ui's Reasoning header
 * (which replaces it once real reasoning deltas arrive). */
function PendingThinking() {
  return (
    <div className="my-2 text-sm text-muted-foreground">
      <div className="inline-flex items-center gap-1.5 px-2 py-1 text-[13px]">
        <Brain size={13} />
        <span className="streaming-caret">Thinking…</span>
      </div>
    </div>
  );
}

export function ChatScreen({ getToken }: { getToken: GetToken }) {
  const sessionId = useMemo(loadOrCreateSessionId, []);
  const [history, setHistory] = useState<AiUIMessage[] | null>(null);

  // Point the shared authed fetch (used by inline tool cards like the Plaid
  // connect card) at this screen's token source.
  useEffect(() => {
    setAuthTokenGetter(() => getToken());
  }, [getToken]);

  // Hydrate persisted history before mounting the chat so refreshes and
  // backend restarts don't blank the transcript. A conversation the principal
  // cannot access (or that does not exist) 404s → treated as empty.
  useEffect(() => {
    let cancelled = false;
    authHeaders(getToken)
      .then((headers) => fetch(`/api/sessions/${sessionId}`, { headers }))
      .then((res) => (res.ok ? res.json() : { messages: [] }))
      .then((data) => {
        if (!cancelled) setHistory((data.messages ?? []) as AiUIMessage[]);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, getToken]);

  if (history === null) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-background text-muted-foreground">
        Loading conversation…
      </div>
    );
  }

  return <Chat sessionId={sessionId} initialMessages={history} getToken={getToken} />;
}

function Chat({
  sessionId,
  initialMessages,
  getToken,
}: {
  sessionId: string;
  initialMessages: AiUIMessage[];
  getToken: GetToken;
}) {
  // Session mode is chosen before the first message and fixed thereafter
  // (immutable server-side). A ref feeds the transport without rebuilding it.
  const [sessionMode, setSessionMode] = useState<SessionMode>("individual");
  const sessionModeRef = useRef<SessionMode>("individual");
  sessionModeRef.current = sessionMode;

  const transport = useMemo(
    () => makeTransport(getToken, () => sessionModeRef.current),
    [getToken],
  );

  const { messages, sendMessage, status, error } = useChat({
    id: sessionId,
    transport,
    messages: initialMessages,
    generateId: () => crypto.randomUUID(),
  });

  const transcriptRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, status, error]);

  const isStreaming = status === "streaming" || status === "submitted";
  const showEmpty = messages.length === 0;
  const lastMessage = messages[messages.length - 1];
  const awaitingResponse =
    isStreaming &&
    lastMessage !== undefined &&
    (lastMessage.role === "user" || !hasVisibleParts(lastMessage as AiUIMessage));

  const startNewChat = () => {
    localStorage.setItem(SESSION_KEY, crypto.randomUUID());
    window.location.reload();
  };

  // Top-level errors come from two paths:
  //   1. `useChat` exposes `error` for transport / parse failures.
  //   2. Stream-level `{type: "error", errorText}` frames are appended as a
  //      part on the assistant message — surface those too.
  const surfacedError = errorMessage(error) || findStreamError(messages as AiUIMessage[]);

  return (
    <div className="flex h-full w-full flex-col bg-background text-foreground">
      <div className="flex items-center justify-end px-3 pt-2">
        <button
          type="button"
          onClick={startNewChat}
          title="New chat"
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <SquarePen className="h-3.5 w-3.5" />
          New chat
        </button>
      </div>
      <div ref={transcriptRef} className="flex-1 overflow-y-auto">
        {/* data-testid/data-role: stable hooks for the Playwright specs. */}
        <div data-testid="transcript" className="mx-auto max-w-3xl px-3 pt-2 pb-2 sm:px-4">
          {showEmpty ? (
            <div className="flex h-[70vh] flex-col items-center justify-center text-center">
              <h1 className="text-2xl font-semibold sm:text-3xl">What can I help with?</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Ask me anything — try <em>"What did I spend this week?"</em>
              </p>
              {/* New-chat mode picker — offered only before the first message,
                  since the mode is immutable once the conversation exists. */}
              <fieldset
                className="mt-6 flex items-center gap-4 text-sm"
                aria-label="Conversation mode"
              >
                <label className="inline-flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="session-mode"
                    aria-label="Individual"
                    checked={sessionMode === "individual"}
                    onChange={() => setSessionMode("individual")}
                  />
                  Individual
                </label>
                <label className="inline-flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="session-mode"
                    aria-label="Joint (household)"
                    checked={sessionMode === "joint"}
                    onChange={() => setSessionMode("joint")}
                  />
                  Joint (household)
                </label>
              </fieldset>
            </div>
          ) : (
            messages.map((m, i) => (
              <div key={m.id ?? i} data-role={m.role} data-message-role={m.role}>
                <Message
                  message={m as unknown as UIMessage}
                  isStreaming={isStreaming && i === messages.length - 1}
                />
              </div>
            ))
          )}
          {!showEmpty && (
            // Once created, the thread's fixed mode is shown (no picker).
            <div className="sr-only" data-testid="session-mode">
              {sessionMode === "joint" ? "Joint (household)" : "Individual"}
            </div>
          )}
          {awaitingResponse && <PendingThinking />}
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
        footerHint="Penny can make mistakes — verify important numbers"
      />
    </div>
  );
}
