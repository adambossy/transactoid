import { useEffect, useMemo, useState } from "react";
import { SquarePen } from "lucide-react";
import { AvatarStack } from "@penny/ui";
import { authHeaders } from "./authFetch";
import { SESSION_KEY, openConversation, startNewChat } from "./session";
import { useHouseholdMembers } from "./useHouseholdMembers";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

interface Conversation {
  id: string;
  title: string | null;
  updated_at: string;
  session_mode: "individual" | "joint";
}

type LoadState =
  | { status: "loading" }
  | { status: "ready"; items: Conversation[] }
  | { status: "error" };

/**
 * Push-style left chat-history drawer.
 *
 * An in-flow `<aside>` whose width animates `w-0 ↔ w-72`, so opening it shifts
 * the page body rather than overlaying it. The inner panel is a fixed `w-72`
 * under the aside's `overflow-hidden`, so its contents never reflow mid-animation.
 * Closed, the panel is `inert` (removed from tab order + pointer events) while
 * still mounted for the width transition.
 *
 * The list is (re)fetched from `GET /api/conversations` each time the drawer
 * opens, so it reflects newly-started or newly-titled chats. Selecting an entry
 * (or "New chat") drives the shared session mechanism in `session.ts`.
 */
export function ChatHistoryDrawer({
  open,
  onClose,
  getToken,
}: {
  open: boolean;
  onClose: () => void;
  getToken: GetToken;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const { members } = useHouseholdMembers(getToken);

  // The joint-thread mark: the other member in front, the viewer behind —
  // "they are in here too". Empty until the household actually has two
  // members (or while the members fetch is loading/failed), so individual
  // entries and solo households render exactly as before.
  const jointStack = useMemo(() => {
    const other = members.find((m) => !m.is_you);
    const self = members.find((m) => m.is_you);
    if (!other || !self) return [];
    return [other, self].map((m) => ({ name: m.display_name, imageUrl: m.image_url }));
  }, [members]);

  // Refetch on each open so the list is fresh (a chat gains its title from the
  // first user message, and new chats appear without a manual reload).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setState({ status: "loading" });
    authHeaders(getToken)
      .then((headers) => fetch("/api/conversations", { headers }))
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", items: (data.conversations ?? []) as Conversation[] });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [open, getToken]);

  // ESC closes the drawer (and restores focus to the toggle via onClose).
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const activeId = localStorage.getItem(SESSION_KEY);

  return (
    <aside
      aria-hidden={!open}
      aria-label="Chat history"
      // Desktop (md+): in-flow, animates width to push the content column.
      // Mobile: fixed overlay (above the backdrop) so it never squishes the chat.
      className={`h-full shrink-0 overflow-hidden border-r border-cream bg-paper transition-[width] duration-300 ease-in-out max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 ${
        open ? "w-72" : "w-0"
      }`}
    >
      {/* Fixed-width inner panel: never reflows while the aside width animates. */}
      <div inert={!open} className="flex h-full w-72 flex-col">
        <div className="flex items-center justify-between px-4 pt-4 pb-2">
          <span className="font-ui text-sm font-medium text-ink">Chats</span>
          <button
            type="button"
            onClick={startNewChat}
            className="inline-flex items-center gap-1.5 rounded-full border border-cream px-3 py-1.5 font-ui text-xs text-ink transition-colors hover:bg-cream-soft"
          >
            <SquarePen className="h-3.5 w-3.5" />
            New chat
          </button>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {state.status === "loading" && (
            <p className="px-2 py-2 font-ui text-sm text-steel">Loading…</p>
          )}
          {state.status === "error" && (
            <p className="px-2 py-2 font-ui text-sm text-steel">Couldn't load chats.</p>
          )}
          {state.status === "ready" && state.items.length === 0 && (
            <p className="px-2 py-2 font-ui text-sm text-steel">No chats yet</p>
          )}
          {state.status === "ready" &&
            state.items.map((conv) => (
              <button
                key={conv.id}
                type="button"
                onClick={() => openConversation(conv.id)}
                aria-current={conv.id === activeId ? "true" : undefined}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left font-ui text-sm text-ink transition-colors hover:bg-cream-soft ${
                  conv.id === activeId ? "bg-cream-soft font-medium" : ""
                }`}
                title={conv.title ?? "New conversation"}
              >
                <span className="min-w-0 flex-1 truncate">
                  {conv.title ?? "New conversation"}
                </span>
                {conv.session_mode === "joint" && jointStack.length >= 2 && (
                  <AvatarStack people={jointStack} size="xs" />
                )}
              </button>
            ))}
        </nav>
      </div>
    </aside>
  );
}
