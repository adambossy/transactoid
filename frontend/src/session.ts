/**
 * Chat-session selection — the single source of truth for *which* conversation
 * the chat screen shows.
 *
 * The active conversation id lives in localStorage under {@link SESSION_KEY};
 * ChatScreen reads it on mount and hydrates `GET /api/sessions/{id}`. Switching
 * conversations (or starting a new one) is therefore just "write a new id here,
 * then load the chat route" — both the chat screen and the history drawer drive
 * that mechanism through the helpers below rather than re-encoding the key.
 */

export const SESSION_KEY = "penny:sessionId";

/** The current session id, minting and persisting a fresh one on first use. */
export function loadOrCreateSessionId(): string {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const fresh = crypto.randomUUID();
  localStorage.setItem(SESSION_KEY, fresh);
  return fresh;
}

/** Point the chat at conversation `id` and (re)load the chat route to show it. */
export function openConversation(id: string): void {
  localStorage.setItem(SESSION_KEY, id);
  window.location.assign("/");
}

/** Start a fresh chat: mint a new session id and (re)load the chat route. */
export function startNewChat(): void {
  openConversation(crypto.randomUUID());
}
