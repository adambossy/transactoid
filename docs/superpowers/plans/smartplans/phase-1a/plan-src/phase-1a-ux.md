---
id: phase-1a-ux
label: UI/UX & E2E
parent: phase-1a
sections: [ui-ux, e2e]
crosslinks: [phase-1a-testing]
---

# UI/UX & end-to-end validation

Phase 1a is backend-only, so its UI/UX bar is a negative one — the user must notice nothing — and its browser validation is a smoke test plus the harness every later phase reuses.

## Requirements

- An existing user opens the app and everything looks and behaves exactly as before — no login wall, no new controls, no added delay.
- If something goes wrong, the user sees the same familiar error message rather than a new or confusing screen.
- The team can prove, through a real browser, that the everyday chat experience still works end to end after the change.

## ui-ux — UI/UX requirements

Sub-project 1 slides the tenancy layer (households, RLS, the dev-stub principal) underneath the current single-user surface, so the goal is that nothing visible changes. An existing user opens the app and the chat screen loads exactly as before — no login wall, no new controls — and sending a message streams the assistant response back with no added latency or regression, even though every query now runs on an RLS-governed, household-scoped connection. No new empty or error states are introduced; any failure still surfaces through the existing error banner rather than a bespoke screen. Verifying that "nothing changed" is the whole job here, so the app shell and chat flow are exercised end to end rather than restyled. New screens use the shared UI template primitives — Header, Footer, Logo, color tokens, type scale — responsive, with loading, empty, and error states.

## e2e — Browser E2E validation

Phase 1a owns the Playwright harness bootstrap: `@playwright/test` stood up in the frontend with a config and fixture that boot the backend in `PENNY_AUTH_MODE=dev` (an env-pinned dev principal on a seeded dev household) plus the vite frontend, so specs run against a live app in headless CI. The first deliverable is a trivial spec proving both servers launch and a real browser renders the SPA; the second is a chat smoke spec that loads the app, sends a message, and asserts a streamed assistant response renders — proving the tenancy/RLS layer left the loading → sending → streaming flow intact through the real UI (see [testing.html](testing.html) for the DB-seam suites). A documented `signInWithClerkTestToken` stub is left for later phases; the harness, seeded households, and Clerk testing tokens all layer on top of this bootstrap in phases 2, 4, and 5.
