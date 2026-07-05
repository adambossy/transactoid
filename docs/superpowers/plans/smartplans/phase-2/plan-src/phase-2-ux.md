---
id: phase-2-ux
label: UI/UX & E2E
parent: phase-2
sections: [ui-ux, e2e]
crosslinks: [phase-2-frontend]
---

# UI/UX & end-to-end validation

Phase 2 introduces the first real user-facing surfaces — a sign-in gate, a user menu, and a session-mode picker — validated end to end with Clerk test-mode sign-in.

## Requirements

- A signed-out spouse sees one clear way in — a Google sign-in screen — and nothing else.
- After signing in, they can tell who they are signed in as, start a chat, pick its privacy, and sign out, all within a consistent frame.
- If their session expires they are smoothly asked to sign in again rather than shown a broken screen, and return to where they were.
- The whole sign-in-to-sign-out journey is proven to work in a real browser before release.

## ui-ux — UI/UX requirements

A signed-out user landing anywhere sees a Google sign-in screen — Clerk's hosted `<SignIn>` wrapped in the app shell — and nothing else, so there is one obvious way in. After signing in with Google, the user lands in the chat and can see who they are signed in as and sign out from a user menu in the header. When starting a new chat, the user picks the session mode — Individual or Household/Joint — before their first message; once a conversation is created that mode is fixed and no longer offered (see [frontend.html](frontend.html)). A user whose session has expired is re-prompted to sign in rather than shown a broken or empty chat, and returns to where they were once re-authenticated. The whole authenticated app is wrapped by the shared app shell so the chat, user menu, and mode picker sit inside a consistent frame. New screens use the shared UI template primitives — Header, Footer, Logo, color tokens, type scale — responsive, with loading, empty, and error states.

## e2e — Browser E2E validation

Headless Playwright specs run against the live backend + frontend, reusing the shared harness bootstrapped in phase 1a and adding a `signInAsTestUser(page, user)` helper built on Clerk's testing tokens / test mode — no interactive Google OAuth — later reused by phases 4 and 5. Test users map to the seeded `users` rows (A and B in household H1) so scoping is exercised end to end. The auth spec drives the full sign-in → send a message → get a response → sign out flow in a real browser, and asserts a protected request while signed out is rejected. A session-mode spec proves the new-chat picker offers accessible Individual/Joint radios and that a joint conversation persists its mode immutably across reload. A conversation-isolation spec, using two separate browser contexts, proves user B cannot open user A's individual conversation URL (404 / no access). Backend runs in Clerk test mode with test keys from CI secrets.
