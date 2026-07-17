import { Show, SignIn, SignUp, UserButton, useAuth } from "@clerk/react";
import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { Wordmark } from "@penny/ui";
import { AppShell } from "./AppShell";
import { BootShell } from "./BootShell";
import { ChunkBoundary } from "./ChunkBoundary";
import { resetHouseholdMembersCache } from "./useHouseholdMembers";

// Lazy so the marketing page's sections/copy/demos load only for signed-out
// visitors at `/` — signed-in users (the common case) never fetch that chunk.
const HomeScreen = lazy(() =>
  import("./home/HomeScreen").then((m) => ({ default: m.HomeScreen })),
);

// Clerk-generated links can target the app root: invitation emails carry
// ?__clerk_ticket=… (consumed by <SignUp>) and hash-routed auth flows resume
// at /#/sso-callback etc. (consumed by <SignIn routing="hash">). Those must
// land on a mounted Clerk component, never the marketing page — and the
// landing CTAs' plain hrefs would drop the ticket. Read once at module scope:
// they arrive only on document loads, never via client-side navigation.
const hasClerkTicket = new URLSearchParams(window.location.search).has("__clerk_ticket");
const hasClerkHashFlow = window.location.hash.startsWith("#/");

// Clerk leaves a synchronous session hint in the __client_uat cookie (a unix
// timestamp, possibly suffixed per publishable key; 0 or absent = no session
// on this browser). Read it at boot so a signed-in user hard-loading `/`
// never sees the marketing page while clerk-js resolves. If the hint is
// stale (cookie says session, Clerk resolves signed-out), the landing simply
// appears once Clerk settles.
const hasSessionHint = document.cookie.split(/;\s*/).some((entry) => {
  const [name, value] = entry.split("=");
  return name.startsWith("__client_uat") && !!value && value !== "0";
});

/**
 * Clerk auth shell. A signed-out visitor sees the landing page at `/` and the
 * hosted <SignUp> / <SignIn> (Google) on the auth paths; a signed-in user sees
 * the household header (name + rename + invite nav + <UserButton>) above the
 * routed screens.
 *
 * Only mounted when Clerk is configured (VITE_CLERK_PUBLISHABLE_KEY set) — see
 * main.tsx. In dev-principal mode the app renders screens without this gate.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { isSignedIn, getToken, userId } = useAuth();

  // Signed-out routing, read via useLocation (not a module-level snapshot) so
  // client-side navigation keeps it current: the marketing home page owns `/`;
  // Clerk's <SignUp> and <SignIn> live at /sign-up and /sign-in (cross-linked,
  // phase 4 open signup); any other signed-out deep link falls back to
  // sign-in. Post-auth, Clerk honors a ?redirect_url= param and otherwise
  // defaults to `/` (fallbackRedirectUrl).
  const path = useLocation().pathname;
  const showSignUp = path.startsWith("/sign-up") || hasClerkTicket;
  const showHome = path === "/" && !hasClerkTicket && !hasClerkHashFlow;

  // Sign-out/sign-in swaps accounts without a page reload; per-account module
  // caches must not survive the swap.
  useEffect(() => {
    resetHouseholdMembersCache();
  }, [userId]);

  // A hinted session clerk-js hasn't confirmed yet (any path): paint the app
  // chrome instead of a blank frame — the handshake still costs its round
  // trip, but the returning user sees "the app" immediately, and never the
  // marketing page. A stale hint degrades to the landing/auth screen once
  // Clerk resolves signed-out.
  if (isSignedIn === undefined && hasSessionHint) {
    return <BootShell />;
  }
  // The landing page is the one surface meant for anonymous reach, so it must
  // not wait for clerk-js: render it at `/` until Clerk positively reports a
  // signed-in session (isSignedIn is undefined while Clerk loads, and never
  // resolves if the script is blocked — the anonymous visitor still gets the
  // page).
  if (showHome && !isSignedIn) {
    return (
      <ChunkBoundary>
        <Suspense fallback={null}>
          <HomeScreen />
        </Suspense>
      </ChunkBoundary>
    );
  }

  return (
    <>
      <Show when="signed-out">
        <div className="auth-gate flex h-full w-full flex-col bg-background">
          <Link to="/" className="inline-flex px-6 py-4 no-underline">
            <Wordmark size={36} className="text-navy" />
          </Link>
          <div className="flex flex-1 items-center justify-center">
            {showSignUp ? (
              <SignUp routing="hash" signInUrl="/sign-in" fallbackRedirectUrl="/" />
            ) : (
              <SignIn routing="hash" signUpUrl="/sign-up" fallbackRedirectUrl="/" />
            )}
          </div>
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
