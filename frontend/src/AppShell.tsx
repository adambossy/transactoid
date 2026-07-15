import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ChatHistoryDrawer } from "./ChatHistoryDrawer";
import { HouseholdHeader } from "./HouseholdHeader";

/** Injected token source: Clerk's getToken in clerk mode, a null no-op in dev. */
type GetToken = () => Promise<string | null>;

/**
 * The app chrome shared by both auth modes: the left chat-history drawer, the
 * header (logo/household name, nav, hamburger), and the routed screen below it.
 * Owns the drawer's open state so the hamburger and the drawer share it.
 *
 * ``actions`` is the header's right slot — Clerk's <UserButton> in clerk mode,
 * omitted in dev — so this shell renders identically without a ClerkProvider.
 * On mobile the drawer overlays (with a tap-to-close backdrop) instead of
 * pushing the content, which would otherwise squish the chat off a phone.
 */
export function AppShell({
  getToken,
  actions,
  children,
}: {
  getToken: GetToken;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    hamburgerRef.current?.focus();
  }, []);

  // Drawer link clicks: below md the drawer overlays (see the md:hidden
  // backdrop below — 768px is Tailwind's md) and must dismiss on navigation;
  // on desktop it pushes content and stays open across client-side switches.
  // The shell owns this policy so the layout split lives in one module.
  const onDrawerNavigate = useCallback(() => {
    if (!window.matchMedia("(min-width: 768px)").matches) closeDrawer();
  }, [closeDrawer]);

  return (
    <div className="relative flex h-full w-full bg-background">
      {/* Mobile-only backdrop behind the overlay drawer; tap to dismiss. */}
      {drawerOpen && (
        <button
          type="button"
          aria-label="Close chat history"
          onClick={closeDrawer}
          className="fixed inset-0 z-30 bg-black/30 md:hidden"
        />
      )}
      <ChatHistoryDrawer
        open={drawerOpen}
        onClose={closeDrawer}
        onNavigate={onDrawerNavigate}
        getToken={getToken}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <HouseholdHeader
          getToken={getToken}
          actions={actions}
          drawerOpen={drawerOpen}
          onToggleDrawer={() => setDrawerOpen((o) => !o)}
          hamburgerRef={hamburgerRef}
        />
        <div className="min-h-0 flex-1">{children}</div>
      </div>
    </div>
  );
}
