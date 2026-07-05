---
id: phase-2-frontend
label: Frontend (Clerk)
parent: phase-2
sections: [gate, token-storage, mode-picker]
crosslinks: [phase-2-backend]
---

# Frontend (Clerk)

Clerk's React SDK handles login and token lifecycle; the app attaches a fresh bearer token to every backend call.

## Requirements

- A spouse signs in with Google and lands directly in their own chat, where they can see who they are signed in as and sign out at any time.
- When starting a chat, they choose whether it is private to them or shared with the household.
- Their session stays protected even if a malicious script runs in the page.

## gate — Auth gate

Wrap the app in `<ClerkProvider>` (`VITE_CLERK_PUBLISHABLE_KEY`). Unauthenticated users see the hosted `<SignIn>` (Google enabled); authenticated users get the existing `ChatScreen` with a `<UserButton>` / sign-out. Attach `Authorization: Bearer <getToken()>` per request (fresh each call) on the AI SDK `/api/chat` transport and the `/api/sessions/{id}` fetch, replacing the old `penny:sessionId` localStorage scheme with server-provided, user-scoped conversation ids.

## token-storage — Token storage & XSS

Configure Clerk for **in-memory** token storage (not `localStorage`) to limit XSS token theft, and audit every place agent/tool output is rendered (transaction descriptions, merchant names, Amazon data) for proper escaping — never `dangerouslySetInnerHTML` with unsanitized content. Token refresh and expiry are Clerk's job; the app just calls `getToken()` and falls back to `<SignIn>` when unauthenticated.

## mode-picker — Session-mode picker

Starting a conversation offers **Individual | Joint** (matching the per-conversation, immutable model on the [conversation page](conversations.html)); the choice is sent on the first message and the backend stamps it. The thread list shows the user's individual conversations plus the household's joint ones.
