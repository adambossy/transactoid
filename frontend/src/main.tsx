import { ClerkProvider, useAuth } from "@clerk/react";
import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { Gallery } from "@penny/ui";
import { registerToolRenderer } from "@adambossy/agent-ui";
import { AppShell } from "./AppShell";
import { AuthGate } from "./AuthGate";
import { ChatScreen } from "./ChatScreen";
import { ChunkBoundary } from "./ChunkBoundary";
import { InviteScreen } from "./InviteScreen";
import { PlaidLinkCard } from "./PlaidLinkCard";
import { ProvidersBillingScreen } from "./ProvidersBillingScreen";
import "./index.css";

// Lazy for the same reason as AuthGate's copy: keep the landing page's chunk
// out of the always-loaded entry bundle.
const HomeScreen = lazy(() =>
  import("./home/HomeScreen").then((m) => ({ default: m.HomeScreen })),
);

// Render the connect_bank_account (new link) and relink_account (update-mode
// re-auth) tool outputs as the same inline Plaid Link card — it branches on the
// output `mode` (`"hosted"` vs `"update"`).
registerToolRenderer("connect_bank_account", PlaidLinkCard);
registerToolRenderer("relink_account", PlaidLinkCard);

// Clerk is active iff a publishable key is configured — the frontend mirror of
// the backend's PENNY_AUTH_MODE clerk/dev split. With no key the app runs in
// dev-principal mode (backend reads PENNY_DEV_*) and sends no bearer token, so
// the phase-1a e2e harness and local dev keep working without Clerk.
const clerkKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

// Dev-only design-system preview: `/ui` renders the @penny/ui Gallery. Guarded by
// import.meta.env.DEV so the route never exists in a production build. The Gallery
// is intentionally auth-free (no ClerkProvider) so the design system stands alone.
const showGallery = import.meta.env.DEV && window.location.pathname.startsWith("/ui");

// Dev-only landing-page preview: `/home` renders the logged-out HomeScreen
// without Clerk, mirroring the `/ui` Gallery pattern, so the marketing page is
// developable and e2e-testable in dev-principal mode. In production the page
// is the signed-out view of `/` (AuthGate).
const showHomePreview = import.meta.env.DEV && window.location.pathname.startsWith("/home");

// The Providers & billing settings screen (phase 2b). Same auth model as chat.
const showBilling = window.location.pathname.startsWith("/settings/providers");

// The invite screen (phase 4): a household member invites new people. Same auth
// model as chat.
const showInvites = window.location.pathname.startsWith("/invites");

// Dev-principal mode: no token (the backend uses the env-pinned principal).
const noToken = async () => null;

function AuthedChat() {
  // Clerk keeps the session token in memory and refreshes it; fetch a fresh one
  // per request. Only mounted inside <ClerkProvider>. getToken is a stable
  // reference — pass it through directly so the screens' useCallback/useMemo/
  // useEffect deps on it don't churn every render.
  const { getToken } = useAuth();
  return <ChatScreen getToken={getToken} />;
}

function AuthedBilling() {
  const { getToken } = useAuth();
  return <ProvidersBillingScreen getToken={getToken} />;
}

function AuthedInvites() {
  const { getToken } = useAuth();
  return <InviteScreen getToken={getToken} />;
}

// The signed-in screen selected by pathname (chat is the default landing).
function authedScreen() {
  if (showBilling) return <AuthedBilling />;
  if (showInvites) return <AuthedInvites />;
  return <AuthedChat />;
}

function devScreen() {
  // Dev-principal mode renders the same app chrome (drawer + header) as the
  // authed path, minus Clerk's <UserButton>, so chat history + nav are present.
  const screen = showBilling ? (
    <ProvidersBillingScreen getToken={noToken} />
  ) : showInvites ? (
    <InviteScreen getToken={noToken} />
  ) : (
    <ChatScreen getToken={noToken} />
  );
  return <AppShell getToken={noToken}>{screen}</AppShell>;
}

function Root() {
  if (showGallery) return <Gallery />;
  if (showHomePreview)
    return (
      <ChunkBoundary>
        <Suspense fallback={null}>
          <HomeScreen />
        </Suspense>
      </ChunkBoundary>
    );
  if (clerkKey) {
    return (
      <ClerkProvider publishableKey={clerkKey}>
        <AuthGate>{authedScreen()}</AuthGate>
      </ClerkProvider>
    );
  }
  return devScreen();
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
