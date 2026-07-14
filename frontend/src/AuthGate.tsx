import { Show, SignIn, SignUp, UserButton, useAuth } from "@clerk/react";
import type { ReactNode } from "react";
import { useLocation } from "react-router";
import { AppShell } from "./AppShell";

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
  // Self-serve signup is open (phase 4): the signed-out view offers Clerk's
  // <SignUp> on the /sign-up path and <SignIn> everywhere else. Both components
  // cross-link, so a visitor can switch between them. Read via useLocation (not
  // a module-level snapshot) so client-side navigation keeps it current.
  const showSignUp = useLocation().pathname.startsWith("/sign-up");
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
        <AppShell getToken={getToken} actions={<UserButton />}>
          {children}
        </AppShell>
      </Show>
    </>
  );
}
