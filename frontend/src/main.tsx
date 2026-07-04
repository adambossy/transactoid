import { ClerkProvider } from "@clerk/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Gallery } from "@penny/ui";
import { ChatScreen } from "./ChatScreen";
import "./index.css";

// Dev-only design-system preview: `/ui` renders the @penny/ui Gallery. Guarded by
// import.meta.env.DEV so the route never exists in a production build. The Gallery
// is intentionally auth-free (no ClerkProvider) so the design system stands alone.
const showGallery = import.meta.env.DEV && window.location.pathname.startsWith("/ui");

function App() {
  if (showGallery) return <Gallery />;

  // Clerk publishable key comes from the Vite env (frontend/.env.local, gitignored).
  // Fail loudly if it's missing rather than rendering a broken auth context.
  const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
  if (!publishableKey) {
    throw new Error("Missing VITE_CLERK_PUBLISHABLE_KEY (set it in frontend/.env.local)");
  }
  return (
    <ClerkProvider publishableKey={publishableKey} afterSignOutUrl="/">
      <ChatScreen />
    </ClerkProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
