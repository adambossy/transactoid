import { ClerkProvider, useAuth } from "@clerk/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { Gallery } from "@penny/ui";
import { registerToolRenderer } from "@adambossy/agent-ui";
import { AppShell } from "./AppShell";
import type { TokenGetter } from "./authFetch";
import { AuthGate } from "./AuthGate";
import { ChatRoute } from "./ChatScreen";
import { InviteScreen } from "./InviteScreen";
import { PlaidLinkCard, PlaidOauthGate } from "./PlaidLinkCard";
import { ProvidersBillingScreen } from "./ProvidersBillingScreen";
import { CONVERSATION_PATH } from "./routes";
import "./index.css";

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

// Dev-principal mode: no token (the backend uses the env-pinned principal).
const noToken = async () => null;

// The signed-in screens, shared verbatim by both auth modes — only the token
// source differs. `/` is always a new chat; a conversation lives at /c/:id;
// anything unmatched goes home (replace, so the dead URL doesn't trap back).
//
// PlaidOauthGate sits ABOVE the route table (it intercepts the bank's OAuth
// return, which lands with no path context) so both chat routes render the
// identical element type — wrapping only `/` would change the tree shape
// across the first-send replace-navigation and remount the in-flight chat,
// defeating the stable key.
function AppRoutes({ getToken }: { getToken: TokenGetter }) {
  return (
    <PlaidOauthGate>
      <Routes>
        <Route path="/" element={<ChatRoute getToken={getToken} />} />
        <Route path={CONVERSATION_PATH} element={<ChatRoute getToken={getToken} />} />
        <Route
          path="/settings/providers/*"
          element={<ProvidersBillingScreen getToken={getToken} />}
        />
        <Route path="/invites/*" element={<InviteScreen getToken={getToken} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </PlaidOauthGate>
  );
}

function AuthedRoutes() {
  // Clerk keeps the session token in memory and refreshes it; fetch a fresh one
  // per request. Only mounted inside <ClerkProvider>. getToken is a stable
  // reference — pass it through directly so the screens' useCallback/useMemo/
  // useEffect deps on it don't churn every render.
  const { getToken } = useAuth();
  return <AppRoutes getToken={getToken} />;
}

function Root() {
  return (
    <Routes>
      {/* Dev-only design-system preview: `/ui` renders the @penny/ui Gallery.
          The route is only registered in dev builds (import.meta.env.DEV), so it
          never exists in production. It sits above the auth split because the
          design system is intentionally auth-free (no ClerkProvider). */}
      {import.meta.env.DEV && <Route path="/ui/*" element={<Gallery />} />}
      <Route
        path="*"
        element={
          clerkKey ? (
            <ClerkProvider publishableKey={clerkKey}>
              <AuthGate>
                <AuthedRoutes />
              </AuthGate>
            </ClerkProvider>
          ) : (
            // Dev-principal mode renders the same app chrome (drawer + header) as
            // the authed path, minus Clerk's <UserButton>, so chat history + nav
            // are present.
            <AppShell getToken={noToken}>
              <AppRoutes getToken={noToken} />
            </AppShell>
          )
        }
      />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Root />
    </BrowserRouter>
  </StrictMode>,
);
