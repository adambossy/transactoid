import { Show, SignIn, SignUp, UserButton, useAuth } from "@clerk/react";
import type { ReactNode } from "react";
import { Logo } from "@penny/ui";
import { AppShell } from "./AppShell";
import { HomeScreen } from "./home/HomeScreen";

// Signed-out routing: the marketing home page owns `/`; Clerk's <SignUp> and
// <SignIn> live at /sign-up and /sign-in (cross-linked, phase 4 open signup);
// any other signed-out deep link (e.g. /settings/providers) falls back to
// sign-in, and post-auth users always navigate to `/` (deep-link restore is a possible follow-up).
const path = window.location.pathname;
const showSignUp = path.startsWith("/sign-up");
const showHome = path === "/";

/**
 * Clerk auth shell. A signed-out visitor sees the landing page at `/` and the
 * hosted <SignUp> / <SignIn> (Google) on the auth paths; a signed-in user sees
 * the household header (name + rename + invite nav + <UserButton>) above the
 * routed screen.
 *
 * Only mounted when Clerk is configured (VITE_CLERK_PUBLISHABLE_KEY set) — see
 * main.tsx. In dev-principal mode the app renders screens without this gate.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();
  return (
    <>
      <Show when="signed-out">
        {showHome ? (
          <HomeScreen />
        ) : (
          <div className="auth-gate flex h-full w-full flex-col bg-background">
            <a href="/" className="flex items-center gap-3 px-6 py-4 no-underline">
              <Logo variant="flat" size={36} />
              <span className="font-serif text-xl font-semibold tracking-[0.22em] text-navy">
                PENNY
              </span>
            </a>
            <div className="flex flex-1 items-center justify-center">
              {showSignUp ? (
                <SignUp routing="hash" signInUrl="/sign-in" forceRedirectUrl="/" />
              ) : (
                <SignIn routing="hash" signUpUrl="/sign-up" forceRedirectUrl="/" />
              )}
            </div>
          </div>
        )}
      </Show>
      <Show when="signed-in">
        <AppShell getToken={getToken} actions={<UserButton />}>
          {children}
        </AppShell>
      </Show>
    </>
  );
}
