---
id: phase-5-engine
label: Onboarding engine
parent: phase-5
sections: [state, triggers, items]
crosslinks: [phase-5-reminders, phase-5-plaid]
---

# Onboarding engine

Deterministic rules decide what to nudge; the [reminder subsystem](reminders.html) carries the nudge to the model.

## Requirements

- Penny nudges me toward the setup steps that actually matter for me, and stops once I've done them or told it to drop them.
- If I dismiss a suggestion it stays gone, but I can still ask for that thing whenever I want.
- Setup nudges only show up in my personal chats, never in a thread I share with family.

## state — State machine

An `onboarding_items` table (RLS-protected) tracks each user's items with exactly three statuses: **pending** (initial), **accepted**, **dismissed**. There is no "active" status — whether an item currently warrants a nudge is a pure function of pending status plus trigger rules, computed per request. The agent's `resolve_onboarding_item` tool sets accepted or dismissed, nothing else. A dismissed item stays dismissed (nudging never resumes), but the user can always just ask for the underlying thing later.

## triggers — Trigger evaluation

On each chat turn in an **individual** conversation, Penny updates counters (categorized-answer turns, corrections), computes which pending items fire, and enqueues **one consolidated onboarding reminder** with override — so the queue always holds exactly the latest state. Joint conversations skip onboarding entirely; personal setup does not belong in a shared thread.

## items — v1 items

| Item | Activates | Cadence |
| --- | --- | --- |
| Connect a bank ([Plaid Link](plaid.html)) | immediately, while unlinked | every turn until resolved |
| Account visibility | first link, household of 2+ | once per session |
| Custom taxonomy | after 3 categorized-answer turns | once per session |
| Merchant rules | after a category correction (or 10 categorized turns) | once per session |
