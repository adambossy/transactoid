import { useEffect, useMemo, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import type { ChatTransport, UIMessage as AiUIMessage } from "ai";
import { AlertCircle, Brain } from "lucide-react";
import { Message, Composer } from "@adambossy/agent-ui";
import type { UIMessage } from "@adambossy/agent-ui";
import { authHeaders, setAuthTokenGetter } from "./authFetch";
import type { TokenGetter } from "./authFetch";
import { OtherUserMessage } from "./OtherUserMessage";
import { loadOrCreateSessionId } from "./session";
import { useHouseholdMembers } from "./useHouseholdMembers";

const MODEL = "gemini-3.5-flash";

type SessionMode = "individual" | "joint";

// Reshape the AI SDK send body to the shape the backend's /api/chat expects,
// attaching a fresh bearer token per request and the (creation-only) session
// mode. The backend ignores sessionMode on an existing conversation.
function makeTransport(
  getToken: TokenGetter,
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
    // Reconnect (GET /api/chat/{id}/stream) after a dropped SSE — attach the
    // bearer token so the resume request authenticates like every other call.
    prepareReconnectToStreamRequest: async ({ api, id, headers }) => ({
      api: `${api}/${id}/stream`,
      headers: { ...headers, ...(await authHeaders(getToken)) },
    }),
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

export function ChatScreen({ getToken }: { getToken: TokenGetter }) {
  const sessionId = useMemo(loadOrCreateSessionId, []);
  const [history, setHistory] = useState<AiUIMessage[] | null>(null);
  // True when the hydrated transcript ends on a user message — i.e. the page was
  // (re)loaded mid-turn (the assistant's reply hasn't been finalized/persisted
  // yet), so the chat should immediately try to resume the live stream. A
  // completed turn always ends on the persisted assistant message.
  const [initialIncomplete, setInitialIncomplete] = useState(false);

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
        if (cancelled) return;
        const msgs = (data.messages ?? []) as AiUIMessage[];
        const last = msgs[msgs.length - 1];
        setInitialIncomplete(last?.role === "user");
        setHistory(msgs);
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

  return (
    <Chat
      sessionId={sessionId}
      initialMessages={history}
      initialIncomplete={initialIncomplete}
      getToken={getToken}
    />
  );
}

function Chat({
  sessionId,
  initialMessages,
  initialIncomplete,
  getToken,
}: {
  sessionId: string;
  initialMessages: AiUIMessage[];
  initialIncomplete: boolean;
  getToken: TokenGetter;
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

  const { messages, sendMessage, status, error, resumeStream } = useChat({
    id: sessionId,
    transport,
    messages: initialMessages,
    generateId: () => crypto.randomUUID(),
  });

  // "Mine vs theirs": a user message is the other member's iff its hydrated
  // sender is known and isn't the viewer. A missing sender (legacy rows,
  // members still loading, live sends) falls through to today's rendering —
  // wrong-styling-by-guess would be worse than the status quo.
  const { members, me } = useHouseholdMembers(getToken);

  // Message id → sender user id, from the hydration payload's senderUserId.
  // Derived here (not threaded as state) and kept beside the AI SDK's message
  // state so useChat's typing stays untouched. Live sends never enter this
  // map, which is correct: the sender of a live turn is always the viewer.
  const senders = useMemo(() => {
    const map: Record<string, string> = {};
    for (const m of initialMessages as Array<{ id?: string; senderUserId?: string | null }>) {
      if (m.id && m.senderUserId) map[m.id] = m.senderUserId;
    }
    return map;
  }, [initialMessages]);

  // Resume a dropped SSE stream. The connection dies when the tab is
  // backgrounded (mobile app-switch) but the sandbox keeps running server-side,
  // so on return we reconnect (GET /api/chat/{id}/stream, replay-then-follow).
  // `wasStreaming` gates it: only resume if a turn was actually in flight and we
  // haven't since seen it finish — the backend 204s otherwise, but this avoids
  // needless replays on ordinary tab switches.
  const statusRef = useRef(status);
  statusRef.current = status;
  const wasStreamingRef = useRef(initialIncomplete);
  useEffect(() => {
    if (status === "submitted" || status === "streaming") wasStreamingRef.current = true;
    else if (status === "ready") wasStreamingRef.current = false;
  }, [status]);

  useEffect(() => {
    // On (re)load mid-turn, reconnect immediately rather than waiting for a
    // visibility change.
    if (initialIncomplete) void resumeStream().catch(() => {});
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (statusRef.current === "submitted" || statusRef.current === "streaming") return;
      if (!wasStreamingRef.current) return;
      void resumeStream().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeStream]);

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

  // Top-level errors come from two paths:
  //   1. `useChat` exposes `error` for transport / parse failures.
  //   2. Stream-level `{type: "error", errorText}` frames are appended as a
  //      part on the assistant message — surface those too.
  const surfacedError = errorMessage(error) || findStreamError(messages as AiUIMessage[]);

  return (
    <div className="flex h-full w-full flex-col bg-background text-foreground">
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
            messages.map((m, i) => {
              const senderId = m.role === "user" ? senders[m.id] : undefined;
              const fromOtherMember = Boolean(senderId && me && senderId !== me.user_id);
              return (
                <div key={m.id ?? i} data-role={m.role} data-message-role={m.role}>
                  {fromOtherMember ? (
                    <OtherUserMessage
                      message={m as unknown as UIMessage}
                      member={members.find((member) => member.user_id === senderId)}
                    />
                  ) : (
                    <Message
                      message={m as unknown as UIMessage}
                      isStreaming={isStreaming && i === messages.length - 1}
                    />
                  )}
                </div>
              );
            })
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
