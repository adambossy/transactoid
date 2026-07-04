# Phase 5 (Penny, Tasks 4–12) — execution decisions

Ambiguities encountered while executing the Phase 5 plan and how they were
resolved. Fail-closed on anything security/privacy-sensitive (RLS, reminder
provenance, joint-session skip) per the orchestrator brief.

## D1 — Reminder/onboarding tables live in the `web` schema, not the finance facade

The plan's Task 4/5 *task bodies* place `QueuedReminder`/`OnboardingItem` on the
finance `penny.adapters.db.models.Base` and use `penny.db.get_db()` /
`session_for(ctx)`. Those task bodies are stale (same staleness as the "migration
018/019" numbers the orchestrator flagged). The plan's own Global Constraints,
the orchestrator brief, and the AGENTS.local.md HARD CONSTRAINT #2 (app data must
stay out of the agent's `run_sql` blast radius) all require these tables to be
**website/app state in the dedicated `web` schema**, exactly like phase-2/2b's
`conversations` / `user_credentials` / `user_billing`.

Decision: models on `WebBase` (`penny/api/persistence/models.py`, `WEB_SCHEMA`);
migrations create `web.onboarding_items` / `web.queued_reminders` with
Postgres-guarded RLS and are SQLite no-ops, mirroring 019/020/021. This is the
fail-closed choice: `run_sql` (finance, read-only role in prod) can never reach
app state.

## D2 — Migration numbers: 022 / 023 (single linear chain)

Per the orchestrator: current head is `021_add_usage_events_and_user_billing`.
Added `022_add_onboarding_items` (down_revision 021) and
`023_add_queued_reminders` (down_revision 022). Ignored the plan's stale
"018/019" text inside Tasks 4/5.

## D3 — Tenant model: owner-scoped within household (no shared arm)

Onboarding items and queued reminders are **personal** app state: a spouse must
not see the other's items (Task 10 RLS test `test_onboarding_items_owner_scoped`),
and onboarding only ever enqueues in individual conversations. RLS predicate is
`household_id = current_household AND owner_user_id = current_user` (owner-scoped,
no `visibility = 'shared'` arm). The web session binds `app.current_household` +
`app.current_user` to the **real** user (never the joint nil sentinel), like
`BillingSession`. On SQLite the store's app-layer `household_id + owner_user_id`
filter is the tenant layer.

## D4 — `build_agent` receives the queue by injection (segregation-preserving)

`agent_factory.build_agent` (agent domain) must not import website persistence.
So it gains `reminders: ReminderQueue | None = None` — typed against the harness
Protocol — and passes it straight to `Agent(reminders=...)`, exactly as it already
does for the injected `usage_pricer`. The website caller (`api/main.py`)
constructs `DbReminderQueue(turn_ctx)` and injects it. Net effect matches the
orchestrator's "build_agent passes reminders=DbReminderQueue(ctx)" without
coupling the agent factory to the web store.

## D5 — Where the queue/engine/tool live vs. the import-boundary guardrail

`DbReminderQueue` → `penny/reminders.py`; onboarding engine+store →
`penny/onboarding.py` (both the file paths the plan/orchestrator named). These
are **website-domain logic** co-located at top-level; they use the web engine via
a shared owner-scoped session helper (`penny/api/persistence/tenant.py`). They are
NOT in the guardrail's guarded set (`penny.api.persistence`, `penny.billing`), so
the `resolve_onboarding_item` @tool (agent domain) may import `penny.onboarding`
and the Plaid exchange service may import `penny.reminders`. The guardrail
(`test_domain_segregation.py`) — which enforces that `penny/tools` and the skills
tree never import the guarded packages — stays green.

Rationale: the PRIMARY segregation guarantee (app data out of `run_sql`'s reach)
is fully honored by D1. `resolve_onboarding_item` is the one sanctioned
agent→app-state write; it goes through the `penny.onboarding` service that owns
the persistence decision, rather than a tool reaching into a store directly. The
reminder queue is only ever injected (D4) or reached through `penny.reminders`.

## D6 — `resolve_onboarding_item` tool return + validation

Validates `action in {accepted, dismissed}` and `item_key in ITEM_KEYS`; updates
the row for `require_request_context().user_id`; returns `{item_key, status}`.
Invalid input returns `{"error": ...}` rather than raising, so a model mistake
surfaces as tool output the agent can recover from (genuine failures — e.g. the
web store being down — still propagate).

## D7 — Plaid exchange reminder content is server-generated only

The `plaid_link` reminder text is built from the institution name and account
count returned by Plaid (server side), never from client input, per the spec's
injection-safety rule. The exchange service takes `client` / `sync` / `queue` as
injectable params (real Plaid client, sync service, and `DbReminderQueue`
defaults resolved lazily) so tests drive it with fakes.

## D9 — `queued_reminders` uses an autoincrement integer PK (not UUID)

The plan specified a UUID PK + `ORDER BY created_at, id`. `CURRENT_TIMESTAMP` is
second-granularity on SQLite and a random UUID is not insertion-ordered, so FIFO
drain would be flaky when reminders land in the same second. Switched to an
autoincrement integer PK ordered by `id` — exact insertion order — matching the
sibling web tables (`conversation_messages.message_id`, `user_credentials.id`).

## D8 — Onboarding trigger `conversation_id` threaded through `TurnSignals`

Once-per-session items (`account_visibility`, `custom_taxonomy`,
`merchant_rules`) stamp `trigger_state["last_nudged_conversation"]` and skip when
it equals the current conversation. `TurnSignals` therefore carries
`conversation_id`. `connect_plaid` fires every turn while unlinked (no
once-per-session guard), matching the spec cadence table.
