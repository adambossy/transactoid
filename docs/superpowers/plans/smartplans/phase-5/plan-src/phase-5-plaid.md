---
id: phase-5-plaid
label: Plaid Link generative UI
parent: phase-5
sections: [inline-flow, exchange, security]
crosslinks: [phase-5-engine]
---

# Plaid Link generative UI

Bank linking is the core onboarding step, so it lives where onboarding lives: inline in the conversation. This is the B-6 rearchitecture from the productionization plan — Link in the frontend, token exchange server-side — with the localhost flow kept for local development.

## inline-flow — The inline flow

When the user accepts the [nudge](engine.html), the agent calls a `connect_bank_account` tool that mints a Plaid link token and returns it as structured output. The frontend registers a tool renderer for that tool name, so a connect card hosting `react-plaid-link` renders inline in the chat — the Vercel generative-UI pattern. Institutions that bounce through OAuth redirect out and back; Link resumes via the received redirect URI, and the conversation itself rehydrates from the store, so the user returns to the same agent state.

## exchange — Server-side exchange and the closing reminder

On success the card posts the public token to an authenticated exchange endpoint. The server exchanges it, encrypts the access token at rest, creates the item and its accounts (owner = the linker, visibility private by default), kicks off the first sync — and **enqueues a reminder**: institution linked, N accounts, sync started, and remind the user they can connect more accounts anytime just by asking. On the next turn Penny says exactly that, naturally. The mechanism closes its own loop.

## security — Security posture

Link tokens are minted only for the authenticated user; the public token never carries privileges and is exchanged server-side; ownership and household come from the request context, never the client; visibility defaults private; the exchange endpoint verifies conversation access before enqueueing; reminder content is generated server-side only, so the flush path cannot inject client text into the model's turn.
