# Phase 5 — Onboarding — Design

**Status:** Approved design (pending written-spec review)
**Date:** 2026-07-03
**Branch:** `feat/account-creation`
**Part of:** [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md)
**Depends on:** [Phase 2 — Auth](2026-07-01-phase-2-auth-social-login-design.md),
[Phase 4 — Signup](2026-07-02-phase-4-signup-ui-design.md) (and phase 1a/1b
foundations)

## Goal

Take a new household from empty to productive — banks linked, visibility
chosen, taxonomy tuned, merchant rules established, first sync done — through a
**progressive, agent-embedded onboarding**: the user chats immediately, and the
agent nudges toward setup steps at deterministic milestones until each is
accepted or dismissed. No wizard.

## Decisions (locked)

- **Plaid Link rearchitecture is in scope** (productionization B-6): Link runs
  in the frontend, token exchange server-side. The **localhost flow stays for
  local development** (mode-switched).
- **Link appears as generative UI**: the `react-plaid-link` picker renders
  inline in the agent chat (Vercel generative-UI pattern via agent-ui's tool
  renderers) when the agent offers it. OAuth redirects leave and return to the
  same conversation state.
- **Onboarding state never enters the system prompt.** Dynamic state is
  delivered as **`<system-reminder>` tags flushed into the next user message**
  — hidden from the UI, visible only to the LLM. The system prompt gains one
  *static* line describing the tags, so prompt caching is preserved.
- **The reminder mechanism is a modular subsystem in agent-harness itself**
  (not Penny-local), modeled on Claude Code's implementation.
- **Hiding reminders from the UI is a first-class agent-ui change**, not an
  accident of the frontend rendering its own copy.
- **`onboarding_items.status ∈ {pending, accepted, dismissed}`** — no `active`
  status. Activation is a deterministic function of pending status + trigger
  rules, evaluated per request; it controls whether a reminder is enqueued.
- The agent reads **only the most recent** system reminder; earlier ones are
  stale by definition.
- Onboarding nudges enqueue only in **individual** conversations (personal
  setup doesn't belong in a joint thread).
- No Plaid webhooks in v1 — sync stays cursor-based (cron/manual).

## Architecture (three repos)

| Repo | Change |
|---|---|
| `~/code/agent-harness` | `ReminderQueue` subsystem + flush into the user message at the run loop |
| `~/code/agent-ui` | First-class hiding of system-reminder content in rendered user messages; a tool renderer hosts Plaid Link inline |
| Penny | Onboarding engine (table + triggers + tool), DB-backed reminder queue, Plaid link-token/exchange endpoints, prompt guidance, frontend renderer |

## Section 1 — System-reminder subsystem (agent-harness)

- `ReminderQueue` protocol + `InMemoryReminderQueue`:
  `enqueue(session_id, kind, content, *, override=True)` — **override replaces
  any queued reminder of the same `kind`** so only the latest state flushes;
  `drain(session_id) -> list[Reminder]` pops all.
- **Flush point:** where the run loop turns the prompt into the user `Message`
  (`core/loop.py` user-prompt append), drained reminders are appended to the
  *same* user message as additional `TextBlock`s wrapped in
  `<system-reminder kind="…">…</system-reminder>`, with `Message.metadata`
  marking which blocks are meta (`{"system_reminder_kinds": [...]}`).
- The queue is injected (`Agent(reminders=...)` or equivalent) so hosts choose
  the implementation; Penny provides a **DB-backed queue** keyed by
  conversation id, so enqueues from HTTP handlers (e.g., the Plaid exchange
  endpoint) survive until the next agent run.
- **Cache safety:** no dynamic system-prompt content. Penny's system prompt
  (promptorium-versioned) gains a static paragraph: reminders are
  system-injected state, not user input; **only the most recent reminder
  reflects current state — disregard earlier ones**.

## Section 2 — First-class UI hiding (agent-ui)

- User-message rendering strips `<system-reminder>…</system-reminder>` spans
  from text parts before display (mirroring Claude Code's transcript-search
  stripping), and never renders a dedicated hidden part type
  (`data-system-reminder`). This guarantees hydrated conversations render clean
  even if stored user messages carry reminder content.
- Exported helper (`stripSystemReminders(text)`) so hosts can reuse the rule
  (e.g., in conversation titles/search).

## Section 3 — Plaid Link as generative UI

- **Agent tool `connect_bank_account`**: creates a Plaid `link_token` for
  `ctx.user_id` (hosted mode) and returns
  `structured_content = {link_token, expiration, mode}`. The existing bridge
  forwards it verbatim.
- **Frontend**: `registerToolRenderer("connect_bank_account", PlaidLinkCard)` —
  an inline card hosting `react-plaid-link`. OAuth redirect support via
  `redirect_uri` + `receivedRedirectUri` resume; the conversation rehydrates
  from the phase-2 store, so the user returns to the same agent state.
- **Exchange**: `onSuccess(public_token)` → authed `POST /api/plaid/exchange`
  (body: `public_token`, conversation id) → server-side exchange → encrypted
  `access_token` (phase-1a cipher) → `plaid_items` + `plaid_accounts` rows
  (`owner_user_id = ctx.user`, `visibility = 'private'`) → first sync kicked
  off → **enqueue a `kind="plaid_link"` reminder**: institution linked, N
  accounts, sync started, and *remind the user they can connect more accounts
  just by asking*. The next turn, the agent relays that naturally.
- Dev keeps the localhost flow behind `PENNY_PLAID_LINK_MODE=hosted|localhost`
  (default `hosted`; dev env sets `localhost`).

## Section 4 — Progressive onboarding engine (Penny)

- **Table `onboarding_items`** (RLS, household term + owner):
  `(household_id, user_id, item_key, status, trigger_state JSON, timestamps)`,
  unique on `(user_id, item_key)`. Status transitions: `pending → accepted` or
  `pending → dismissed`, via the agent tool only.
- **Tool `resolve_onboarding_item(item_key, action)`** — `action ∈
  {accepted, dismissed}`, nothing else. Everything stays revisitable: a user
  who dismissed an item and later wants it simply asks, and the agent performs
  the underlying action directly (link a bank, adjust taxonomy, add a rule) —
  no status reset needed; the item stays `dismissed` so nudging never resumes.
- **Trigger evaluation** (deterministic, per chat request, individual
  conversations only): update counters in `trigger_state`, compute the set of
  pending items whose rule fires, and enqueue **one consolidated
  `kind="onboarding"` reminder** (override=True) describing them, with guidance
  to nudge naturally, at most once per turn, without repeating verbatim.
- **v1 items + rules:**

| item_key | Activates | Cadence |
|---|---|---|
| `connect_plaid` | immediately, while the user has no linked items | every turn until accepted/dismissed |
| `account_visibility` | ≥1 item linked and household has ≥2 members | once per session |
| `custom_taxonomy` | after 3 turns whose responses included categorized transactions | once per session |
| `merchant_rules` | after the user corrects a categorization (or 10 categorized turns) | once per session |

- First sync is not a nudge — the `plaid_link` reminder plus the agent's sync
  tools report progress.

## UI/UX Requirements

- As a new user, I land straight in the chat and start talking to Penny; the
  onboarding nudges arrive as natural conversational messages inline in the
  transcript — there is no separate wizard, stepper, or setup screen.
- As a user prompted to connect a bank, I see the **inline Plaid Link connect
  card** rendered as generative UI within the agent's message, styled with the
  shared template, and I launch Plaid from it without leaving the conversation.
- As a returning user, I can reach a "Connect accounts" surface to link more
  banks and toggle each account's visibility between private and shared, and I
  can get there by simply asking the agent.
- As a user who just linked a bank, I see clear first-sync progress indication
  so I know transactions are being pulled in and roughly how far along it is.
- As any user, I never see the system-reminder-driven onboarding state in the
  transcript — the reminders are invisible, and only the agent's natural
  reactions to them appear.

All new screens use the **shared UI template primitives** (Header, Footer, Logo,
color tokens, type scale, font stack) — no bespoke styling. Screens are
responsive (mobile and desktop) and handle loading, empty, and error states, and
the app shell (header/footer) is consistent across screens.

## Security

- `link_token` minted only for the authenticated user; `public_token` exchange
  is server-side; access tokens encrypted at rest; item/account ownership from
  `ctx`, never the client. Visibility defaults private.
- The exchange endpoint validates that the conversation being resumed belongs
  to the caller (phase-2 access check) before enqueueing its reminder.
- `onboarding_items` and the reminder-queue table carry the standard RLS
  policies. Reminder *content* is generated server-side only — never from
  client input — so the flush path cannot be used to inject attacker text into
  the LLM turn.

## Testing strategy

- **agent-harness:** unit — enqueue/override/drain semantics; flush appends
  wrapped blocks to the user message and empties the queue; no reminders → no
  extra blocks.
- **agent-ui:** unit — `stripSystemReminders` and user-message rendering hide
  reminder spans/parts.
- **Penny:** trigger determinism (same state → same activation set); status
  transitions via the tool; consolidated override enqueue (two evaluations →
  one queued reminder); exchange endpoint (faked Plaid client) creates
  encrypted item + private accounts + enqueues `plaid_link`; joint
  conversations enqueue nothing; Postgres RLS on both new tables; e2e — a chat
  turn's outgoing user message contains the reminder text (bridge-level
  assertion) while the stored/rendered message does not.
- Manual: sandbox Plaid Link end-to-end incl. an OAuth institution redirect.

## Out of scope

- Plaid webhooks (cursor-based sync remains).
- Wizard UI of any kind; taxonomy/rule *editors* (the agent handles both
  conversationally).
- Nudge personalization/ML — cadences are fixed rules in v1.
- Applying the reminder subsystem to other Penny features (memory staleness,
  todo-style nudges) — natural follow-ons once the mechanism exists.

## Future work

- Evolve cadences/items from usage; add reminder kinds for sync completion and
  report readiness; revisit joint-conversation onboarding once household-level
  items exist (e.g., shared taxonomy setup).
