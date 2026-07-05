import { useCallback, useEffect, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { Menu } from "lucide-react";
import { Header, IconButton } from "@penny/ui";
import { authHeaders } from "./authFetch";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

interface Me {
  user_id: string;
  email: string;
  household_id: string;
  household_name: string;
}

/**
 * The signed-in header: the PENNY wordmark, the caller's household name (click to
 * rename inline, persisted via PATCH /api/household), nav to Chat / Invite, and
 * the Clerk <UserButton>. Fetches GET /api/me on mount — the first call after
 * signup is what triggers backend auto-provisioning, so the household name is
 * guaranteed to resolve here.
 */
export function HouseholdHeader({
  getToken,
  drawerOpen,
  onToggleDrawer,
  hamburgerRef,
  actions,
}: {
  getToken: GetToken;
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  hamburgerRef: RefObject<HTMLButtonElement | null>;
  // Right-side actions — Clerk's <UserButton> in clerk mode, omitted in dev.
  actions?: ReactNode;
}) {
  const [me, setMe] = useState<Me | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const load = useCallback(async () => {
    const res = await fetch("/api/me", { headers: await authHeaders(getToken) });
    if (res.ok) setMe(await res.json());
  }, [getToken]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    const name = draft.trim();
    if (!name) return;
    const res = await fetch("/api/household", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...(await authHeaders(getToken)) },
      body: JSON.stringify({ name }),
    });
    if (res.ok) {
      setEditing(false);
      await load();
    }
  }

  const householdName = (
    <span className="flex items-center gap-2">
      {editing ? (
        <>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
              if (e.key === "Escape") setEditing(false);
            }}
            autoFocus
            data-testid="household-name-input"
            className="rounded-full border border-cream bg-paper px-3 py-1 font-ui text-sm text-ink focus:outline-none"
          />
          <button
            onClick={() => void save()}
            data-testid="household-name-save"
            className="cursor-pointer font-ui text-sm text-navy underline"
          >
            Save
          </button>
        </>
      ) : (
        <button
          onClick={() => {
            setDraft(me?.household_name ?? "");
            setEditing(true);
          }}
          data-testid="household-name"
          className="cursor-pointer font-ui text-sm font-medium text-ink hover:underline"
          title="Rename household"
        >
          {me?.household_name ?? "…"}
        </button>
      )}
    </span>
  );

  return (
    <Header
      leading={
        <IconButton
          ref={hamburgerRef}
          aria-label={drawerOpen ? "Close chat history" : "Open chat history"}
          aria-expanded={drawerOpen}
          onClick={onToggleDrawer}
        >
          <Menu className="h-5 w-5" />
        </IconButton>
      }
      nav={
        <>
          {householdName}
          <a href="/" className="hover:underline">
            Chat
          </a>
          <a href="/invites" data-testid="nav-invites" className="hover:underline">
            Invite
          </a>
        </>
      }
      actions={actions}
    />
  );
}
