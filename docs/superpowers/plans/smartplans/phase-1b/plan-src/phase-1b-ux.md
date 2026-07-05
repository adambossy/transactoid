---
id: phase-1b-ux
label: UI/UX & E2E
parent: phase-1b
sections: [ui-ux, e2e]
crosslinks: [phase-1b-versioning]
---

# UI/UX & end-to-end validation

Phase 1b moves the workspace off the local filesystem, so it too is invisible infrastructure — memory and reports must keep surfacing naturally, proven by a round-trip through the real UI.

## Requirements

- A user who relies on the agent's memory and past reports keeps seeing them surface naturally in conversation after the storage change.
- Nothing about the chat experience changes and no new error screens appear; any failure shows the same familiar message.
- The team can prove, through a real browser, that a saved memory survives and comes back in a later conversation.

## ui-ux — UI/UX requirements

The workspace hybrid (Postgres manifest + R2 blobs) replaces `~/.transactoid` as invisible infrastructure — never a screen of its own. A user who relies on the agent's memory and past reports keeps seeing those surface naturally in conversation after the store moves onto the hybrid; memory, rules, and reports appear in agent replies just as they did from the local filesystem. No new empty or error states arise from this work; any failure still surfaces through the existing error banner. The bar is again a negative one: the store round-trips correctly and nothing about the chat surface changes. New screens use the shared UI template primitives — Header, Footer, Logo, color tokens, type scale — responsive, with loading, empty, and error states.

## e2e — Browser E2E validation

A single Playwright spec proves the workspace round-trips through the real UI: the agent saves a memory in one chat and recalls it in a later chat, which only works if the R2 blob upload and Postgres manifest CAS actually committed and re-materialized across runs (see [versioning.html](versioning.html) for the commit/CAS mechanics). It reuses the phase-1a harness — dev-mode backend plus vite with the pinned dev principal — adding no new scaffolding, and drives the flow in a real headless browser: run 1 asks the agent to remember a fact and flush it; a reload re-materializes the workspace head from R2 + manifest; run 2 asks the agent to recall the fact and asserts it comes back. The spec is gated behind the same model-key guard as the chat smoke spec, since it needs a model that will actually call the memory tool. Later phases layer Clerk testing tokens onto this same harness.
