import { SignedIn, SignedOut, SignIn, UserButton } from "@clerk/clerk-react";
import type { ReactNode } from "react";

/**
 * Clerk auth shell. A signed-out user sees only the hosted <SignIn> (Google);
 * a signed-in user sees a header with a <UserButton> (sign-out) above the chat.
 *
 * Only mounted when Clerk is configured (VITE_CLERK_PUBLISHABLE_KEY set) — see
 * main.tsx. In dev-principal mode the app renders the chat without this gate.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  return (
    <>
      <SignedOut>
        <div className="auth-gate flex h-full w-full items-center justify-center bg-background">
          <SignIn routing="hash" />
        </div>
      </SignedOut>
      <SignedIn>
        <div className="flex h-full w-full flex-col bg-background">
          <header className="auth-header flex items-center justify-end px-3 pt-2">
            <UserButton />
          </header>
          <div className="min-h-0 flex-1">{children}</div>
        </div>
      </SignedIn>
    </>
  );
}
