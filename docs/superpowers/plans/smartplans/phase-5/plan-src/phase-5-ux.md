---
id: phase-5-ux
label: UI/UX & E2E
parent: phase-5
sections: [ui-ux, e2e]
crosslinks: [phase-5-plaid]
---

# UI/UX & end-to-end validation

Phase 5 delivers conversational onboarding and the inline Plaid Link card, validated end to end up to the card render and a stubbed exchange.

## Requirements

- I land straight in the chat and get onboarded through natural conversation, with no separate wizard, stepper, or setup screen.
- When prompted to connect a bank, I can launch it from an inline card without ever leaving the conversation.
- I can add more banks and choose whether each account is private or shared simply by asking Penny.
- The hidden onboarding state never appears in my transcript — I only see Penny's natural reactions to it.

## ui-ux — UI/UX requirements

A new user lands straight in the chat and starts talking to Penny; onboarding nudges arrive as natural conversational messages inline in the transcript — there is no separate wizard, stepper, or setup screen. A user prompted to connect a bank sees the inline Plaid Link connect card rendered as generative UI within the agent's message, styled with the shared template, and launches Plaid from it without leaving the conversation (see [plaid.html](plaid.html)). A returning user can reach a "Connect accounts" surface to link more banks and toggle each account's visibility between private and shared, simply by asking the agent. A user who just linked a bank sees clear first-sync progress indication. The system-reminder-driven onboarding state is never visible in the transcript — only the agent's natural reactions to the invisible reminders appear. New screens use the shared UI template primitives — Header, Footer, Logo, color tokens, type scale — responsive, with loading, empty, and error states.

## e2e — Browser E2E validation

Headless Playwright specs reuse the shared harness from phase 1a and `signInAsTestUser` from phase 2, driving a signed-in test user in a real browser. Because Plaid Link runs in sandbox and its hosted popup cannot be driven headlessly, the specs assert up to the inline card render plus a stubbed `/api/plaid/exchange` (via `page.route`), leaving the full sandbox link-through as a manual step. An onboarding-nudge spec signs in a fresh user with zero linked banks, sends a first message, and asserts the agent's response nudges to connect a bank, the inline `connect_bank_account` card renders, and after a stubbed successful exchange no new nudge or card reappears. A Plaid-card spec proves the inline card renders from `mode: "hosted"` tool output and enables its "Connect a bank" button once the link token is present. Backend runs against a sandbox/scripted setup.
