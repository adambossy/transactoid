import { useEffect, useState } from "react";
import { SquarePen } from "lucide-react";
import { Link, useMatch } from "react-router";
import { authHeaders } from "./authFetch";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

interface Conversation {
  id: string;
  title: string | null;
  updated_at: string;
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

  // The open conversation comes from the URL — the drawer may render outside
  // the matched route, so match the path directly rather than useParams.
  const activeId = useMatch("/c/:id")?.params.id;

  // Below md the drawer is an overlay; navigating should dismiss it. On
  // desktop it pushes content and stays open across client-side switches.
  const closeIfOverlay = () => {
    if (!window.matchMedia("(min-width: 768px)").matches) onClose();
  };

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
          <Link
            to="/"
            onClick={closeIfOverlay}
            className="inline-flex items-center gap-1.5 rounded-full border border-cream px-3 py-1.5 font-ui text-xs text-ink transition-colors hover:bg-cream-soft"
          >
            <SquarePen className="h-3.5 w-3.5" />
            New chat
          </Link>
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
              <Link
                key={conv.id}
                to={`/c/${conv.id}`}
                onClick={closeIfOverlay}
                aria-current={conv.id === activeId ? "true" : undefined}
                className={`block w-full truncate rounded-lg px-2 py-2 text-left font-ui text-sm text-ink transition-colors hover:bg-cream-soft ${
                  conv.id === activeId ? "bg-cream-soft font-medium" : ""
                }`}
                title={conv.title ?? "New conversation"}
              >
                {conv.title ?? "New conversation"}
              </Link>
            ))}
        </nav>
      </div>
    </aside>
  );
}
