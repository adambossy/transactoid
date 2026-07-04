import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider, useAuth } from "@clerk/clerk-react";
import { Gallery } from "@penny/ui";
import { AuthGate } from "./AuthGate";
import { ChatScreen } from "./ChatScreen";
import "./index.css";

// Clerk is active iff a publishable key is configured — the frontend mirror of
// the backend's PENNY_AUTH_MODE clerk/dev split. With no key the app runs in
// dev-principal mode (backend reads PENNY_DEV_*) and sends no bearer token, so
// the phase-1a e2e harness and local dev keep working without Clerk.
const clerkKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

// Dev-only design-system preview: `/ui` renders the @penny/ui Gallery. Guarded by
// import.meta.env.DEV so the route never exists in a production build.
const showGallery = import.meta.env.DEV && window.location.pathname.startsWith("/ui");

// Dev-principal mode: no token (the backend uses the env-pinned principal).
const noToken = async () => null;

function AuthedChat() {
  // Clerk keeps the session token in memory and refreshes it; fetch a fresh one
  // per request. Only mounted inside <ClerkProvider>.
  const { getToken } = useAuth();
  return <ChatScreen getToken={() => getToken()} />;
}

function Root() {
  if (showGallery) return <Gallery />;
  if (clerkKey) {
    return (
      <ClerkProvider publishableKey={clerkKey}>
        <AuthGate>
          <AuthedChat />
        </AuthGate>
      </ClerkProvider>
    );
  }
  return <ChatScreen getToken={noToken} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
