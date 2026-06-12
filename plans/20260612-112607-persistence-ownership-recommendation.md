# Recommendation: App-owned persistence, keyed by `session_id`. Do not put it in the harness.

Companion decision doc for `plans/20260612-085245-persist-chat-conversations.md`. Answers: should the conversation/message persistence layer live inside `agent-harness` or in the Penny app — and how do app-level accounts link to conversation/message rows?

## Verdict

Build the UI-faithful conversation/message store **entirely in Penny app code** (the website domain), exactly as the plan's §0.5 already proposes. **Reinforce §0.5, don't revise it.** Do not move persistence into `agent-harness`, and — importantly — do **not** even use the harness `Session` Protocol as the linking seam (the dependency-inversion option). Link accounts to conversations with **real foreign keys inside one app-owned database**, using the harness `session_id` only as a *shared identifier value*, never as a cross-store key.

The single most important architectural fact: **the harness transcript and the UI record are different data with different owners and different fidelity.** The harness `SqliteSession` stores `Message` pydantic models — the *model's working context* — and `ToolResultBlock.content` is flattened to `content_to_text(result)`, dropping `structured_content`, the `tool-output-error` distinction, and stream-level `Error` frames (confirmed in `agent_harness/sessions/sqlite.py` storing `m.model_dump_json()`, and `loop.py` appending `final_message`/`tool_msg`). The thing we want to persist for accounts and the UI does not exist in the harness's data model. So "should persistence live in the harness" partly answers itself: the harness doesn't have the data, and giving it the data would mean teaching a general-purpose library about AI-SDK UI frames and user accounts.

## Rationale — what breaks under the rejected options

**Rejected option A — persistence lives inside agent-harness.** Fails three principles at once:

- *No leaky abstractions / library genericity.* `agent-harness` is its own repo, editable-installed, usable by apps other than Penny ("Penny never reimplements these"). Persisting the UI record there forces the harness to model AI-SDK-UI part shapes (`tool-output-available`, `errorText`, reasoning parts) — a Vercel-AI-SDK-specific concept with no place in a provider-agnostic loop. Supporting the accounts link forces a `user_id`/`account_id` column — one app's auth schema pushed into a shared library.
- *Single source of truth.* The harness already owns `sessions.db` as model working memory. A second richer transcript inside the harness creates two overlapping-but-divergent model-facing stores in one package — the drift §0 is trying to escape.
- *Acyclic dependencies.* Accounts are an app concept. A harness that knows about accounts depends on the app's domain while the app depends on the harness — a cycle across a package boundary.

**Rejected option B — dependency inversion via the harness `Session` Protocol** (app implements a custom `Session` that also writes UI rows + account linkage). The seductive wrong answer. The `Session` Protocol (`agent_harness/core/memory.py`) speaks in `Message`/`RunStateSnapshot` — the lossy model-side types. An app `Session` implementation receives `add_messages([final_message])` with `content_to_text`-flattened tool results — **the same lossy data the bridge was created to bypass.** You'd capture UI history at the wrong layer, re-introducing the exact fidelity loss §0 identifies, just to reuse a hook. The bridge already sees `ToolExecEnd.result.structured_content` verbatim (`bridge.py::_serialize_tool_output`); the `Session` seam never does. Dependency inversion is the right *pattern* for a generic persistence hook, but the harness's hook is shaped for model memory, not UI fidelity — wrong seam for *this* data. (Leave `sessions.db` alone; the seam stays right for what it already does.)

**Why app-owned wins.** The bridge is already website code that sees full fidelity; capturing there makes "what we persist == what we streamed" true by construction. The store is plain SQLAlchemy the app fully controls, so accounts get real FKs. The harness stays generic — no UI-SDK leakage, no accounts leakage.

## The elegant linking design

**One app-owned database, three tables, real foreign keys. `session_id` is a shared *value*, not a cross-store key.**

The move that dissolves the "cross-package FK has no referential integrity" tension: **conversations and accounts both live in the website store, so the FK is intra-database and fully enforced.** The harness `session_id` is reused verbatim as the `conversations` PK (plan §1) — so the harness `sessions.db` row and the app `conversations` row share an identifier *by value*. There is intentionally **no** FK from app tables into `sessions.db`; that cross-store edge is the one without referential integrity, and we simply don't draw it. The harness transcript is a cache of model context keyed by the same string; deleting either side leaves the other intact.

```
  ┌─────────────── Website-owned DB / schema (penny_web.db / Neon `web`) ───────────────┐
  │                                                                                      │
  │   accounts                conversations                conversation_messages         │
  │   ┌──────────────┐        ┌────────────────────┐       ┌──────────────────────────┐  │
  │   │ account_id PK│◄───┐   │ conversation_id PK │◄──┐   │ message_id PK            │  │
  │   │ email        │    │   │  (= harness         │   │   │ conversation_id FK ──────┼──┘
  │   │ created_at   │    └───┤   session_id value) │   └───┤ client_message_id        │
  │   └──────────────┘ FK     │ account_id FK ──────┘       │ seq, role, parts(JSON)   │
  │            account_id     │ title, *_at         │       │ status                   │
  │            ondelete=      └────────────────────┘        └──────────────────────────┘
  │            CASCADE             ▲                                                      │
  └───────────────────────────────┼──────────────────────────────────────────────────────┘
                                   │ same string, NO FK (cross-store)
                       ┌───────────┴──────────────┐
                       │  harness sessions.db      │   ← model working memory; harness-owned
                       │  messages(session_id,...) │     leave as-is; lossy by design
                       └───────────────────────────┘
```

**`accounts`** (new, app-owned; ships when accounts arrive): `account_id` PK (String/UUID), auth fields (`email`, …).

**`conversations`** (plan §1, with one added column):

| column | type | notes |
|---|---|---|
| `conversation_id` | String PK | = client UUID = harness `session_id` value |
| `account_id` | String FK → `accounts.account_id`, `ondelete=CASCADE`, indexed, **nullable today** | The link. Nullable now (single-user); enforced NOT NULL when accounts land. |
| `title`, `created_at`, `updated_at`, `last_message_at` | | as plan |

**`conversation_messages`** — exactly as plan §1 (FK → `conversations`, `ondelete=CASCADE`).

**Referential integrity & deletion semantics:**
- Account deletion → `accounts` CASCADEs to `conversations` → CASCADEs to `conversation_messages`. One DELETE removes the user's entire UI history with DB-enforced integrity — the property you *cannot* get if conversations live in the harness and accounts in the app.
- The harness `sessions.db` rows are *orphaned by value* on account deletion. Acceptable: they're model-context cache, contain finance data the user was already viewing, and can be swept best-effort via `session.clear()` in the app's delete handler (the app holds the `session_id`). That sweep is cleanup, **not** an integrity guarantee — the deliberate price of keeping the harness account-agnostic.

**Who writes the link:** the website, where it does everything else — `main.py::chat` calls `ensure_conversation(conversation_id, account_id=current_account)`. The harness never sees `account_id`. One-directional dependency (website → harness), satisfying §0.5.

## Impact on the existing plan (endorses it; concrete deltas)

- **§0.5** — No change to the stance; add one sentence making the *seam choice* explicit: "We capture at the bridge, **not** via a custom harness `Session` implementation, because the `Session` Protocol only carries the lossy model-side `Message` type." Pre-empts a future contributor 'simplifying' by implementing `Session` and silently reintroducing lossiness.
- **§1 data model** — Promote the parenthetical `user_id` note to a first-class **`account_id` FK column, nullable now**, with the CASCADE chain documented. Frame as "ship the nullable column now so the accounts feature is a pure data-population + NOT-NULL change, never a structural one." Matters because of §4: `create_all` can't add columns to a populated table, so adding `account_id` *after* data exists forces alembic; adding it now (empty/nullable) avoids that.
- **§2 capture** — No change (bridge capture is correct precisely because it's the only full-fidelity seam). Thread the `account_id` argument through `ensure_conversation`.
- **§4 schema** — Add `accounts` to the website `Base`/`create_all`. Reaffirm the `conversations.account_id` FK is intra-`web`-schema (real, enforced). Explicitly note the **absence** of any FK into `sessions.db` is intentional. Note `account_id` nullable-now as the lever keeping accounts an additive (no-alembic) rollout.
- **§5 risks/guardrail** — The segregation guardrail (`tests/test_domain_segregation.py`) covers the import boundary. Add: the website persistence package may import `agent_harness.sessions` *only* for the legacy `messages_to_ui` backfill read — and must never implement `agent_harness.core.memory.Session`.

## Strongest counterargument (and why it loses)

*"Two stores keyed by the same `session_id` with no enforced link — that's a dual source of truth."* They overlap but are **not** the same fact: `sessions.db` is the model's lossy working context (harness-owned, format may churn); `conversation_messages` is the UI's canonical faithful record (app-owned). Single-source-of-truth means each *fact* has one home — and the UI-faithful fact (with `structured_content`, error distinctions) lives in exactly one place: the app store. The harness store is a derived, lossy projection the app never reads except for one-time legacy backfill. Two stores of *different* data keyed by a shared id is not dual-source-of-truth; merging them (option A/B) is what would create the leaky, drift-prone coupling.

## Evidence
- `~/code/agent-harness/agent_harness/sessions/sqlite.py` — `SqliteSession` stores `Message.model_dump_json()`; `_append_payloads` is the `COALESCE(MAX(ord),-1)+1` seq pattern the plan mirrors.
- `~/code/agent-harness/agent_harness/core/memory.py` — `Session` Protocol speaks only `Message`/`RunStateSnapshot` (the lossy seam).
- `~/code/agent-harness/agent_harness/core/loop.py` — where the harness persists user/assistant/tool messages.
- `~/code/agent-harness/agent_harness/core/agent.py` — `Agent.session: Session | None`, the pluggable seam.
- `backend/penny/api/bridge.py` — `_serialize_tool_output` and `_translate`: the only full-fidelity capture point, including `tool-output-error`.
- `backend/penny/api/main.py` — `_get_session` (harness `sessions.db`), hydration via `messages_to_ui`, `chat_id` flow.
- `backend/penny/bootstrap.py`, `backend/penny/adapters/db/` — the finance `Base`/facade the agent links against pervasively (kept conversation-free by §0.5).
