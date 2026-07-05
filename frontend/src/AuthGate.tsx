import { Show, SignIn, SignUp, useAuth } from "@clerk/react";
import type { ReactNode } from "react";
import { useCallback, useRef, useState } from "react";
import { ChatHistoryDrawer } from "./ChatHistoryDrawer";
import { HouseholdHeader } from "./HouseholdHeader";

// Self-serve signup is open (phase 4): the signed-out view offers Clerk's
// <SignUp> on the /sign-up path and <SignIn> everywhere else. Both components
// cross-link, so a visitor can switch between them.
const showSignUp = window.location.pathname.startsWith("/sign-up");

/**
 * Clerk auth shell. A signed-out visitor sees the hosted <SignUp> / <SignIn>
 * (Google); a signed-in user sees the household header (name + rename + invite
 * nav + <UserButton>) above the routed screen.
 *
 * Only mounted when Clerk is configured (VITE_CLERK_PUBLISHABLE_KEY set) — see
 * main.tsx. In dev-principal mode the app renders screens without this gate.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();

  // The chat-history drawer's open state is owned here so the hamburger (in the
  // header) and the push-style drawer (a sibling column) share it. Closing
  // restores focus to the hamburger for keyboard users (e.g. after ESC).
  const [drawerOpen, setDrawerOpen] = useState(false);
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    hamburgerRef.current?.focus();
  }, []);

  return (
    <>
      <Show when="signed-out">
        <div className="auth-gate flex h-full w-full items-center justify-center bg-background">
          {showSignUp ? (
            <SignUp routing="hash" signInUrl="/" />
          ) : (
            <SignIn routing="hash" signUpUrl="/sign-up" />
          )}
        </div>
      </Show>
      <Show when="signed-in">
        {/* Push layout: the in-flow drawer aside shifts the header+content
            column right as it animates open, rather than overlaying it. */}
        <div className="flex h-full w-full bg-background">
          <ChatHistoryDrawer open={drawerOpen} onClose={closeDrawer} getToken={getToken} />
          <div className="flex min-w-0 flex-1 flex-col">
            <HouseholdHeader
              getToken={getToken}
              drawerOpen={drawerOpen}
              onToggleDrawer={() => setDrawerOpen((o) => !o)}
              hamburgerRef={hamburgerRef}
            />
            <div className="min-h-0 flex-1">{children}</div>
          </div>
        </div>
      </Show>
    </>
  );
}
