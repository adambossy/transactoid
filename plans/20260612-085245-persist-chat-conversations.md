# Implementation Plan: Persisting Chat Conversations and Messages

## 0. Context discovered (verified against code)

- **Entry point** `backend/penny/api/main.py`: `POST /api/chat` builds a per-request `Agent` bound to a per-`chat_id` `SqliteSession` (harness `sessions.db` in the workspace, separate from `penny.db`), then streams via `stream_agent(agent, prompt)`. `GET /api/sessions/{id}` hydrates by reading `session.get_messages()` and passing through `messages_to_ui`.
- **Bridge** `backend/penny/api/bridge.py`: subscribes to the harness `InMemoryEventBus`, runs the agent, and maps each `Event` to one or more AI SDK UI-message-stream frames. This is the only place that sees the full fidelity of every part — notably `ToolExecEnd.result.structured_content` (emitted verbatim via `_serialize_tool_output`) and the `tool-output-error` distinction.
- **Harness already persists a transcript** to `sessions.db` incrementally inside the loop (`agent_harness/core/loop.py`): user `Message` at `PrepareTurn`, each assistant `final_message`, each `tool_msg`. So conversation continuity for the *model* already survives restarts.
- **Critical gap (the reason to persist ourselves):** the harness transcript is **lossy for the UI**. `ToolResultBlock.content` is `content_to_text(result)` — a flat string. The rich `structured_content` (chart specs, SQL result tables, MCP structured output) that the bridge sends to the browser is **not stored**. Today's `messages_to_ui` (`backend/penny/api/hydration.py`) recovers tool output only by `json.loads`-ing that string — it round-trips by accident when a tool happened to emit JSON-as-text, and silently degrades otherwise. Stream-level `Error` frames and the `tool-output-error` vs `tool-output-available` distinction are also **absent** from the transcript. Commit `9dac604` patched one symptom of this lossiness (thinking summaries were dropped) by special-casing `ThinkingBlock`; we should stop patching the lossy path and instead capture the UI-faithful frame stream.
- **Schema reality** `backend/penny/bootstrap.py` calls `db.create_schema()` → `Base.metadata.create_all(engine)` on startup. **No alembic** (despite stale references in facade docstrings). New tables are purely additive, so `create_all` picks them up for free on both SQLite (`penny.db`) and Neon Postgres.
- **Frontend** `frontend/src/ChatScreen.tsx`: `sessionId` is a `crypto.randomUUID()` persisted in `localStorage` under `penny:sessionId`; "New chat" just rolls a new UUID and reloads. It already hydrates from `GET /api/sessions/{id}` before mounting `useChat`. There is **no conversation list** and no titling.

**Design stance:** Persist Penny's own UI-faithful record captured **at the bridge** as frames stream, in a **website-owned, agent-isolated** store (see §0.5) — *not* the shared finance DB/facade. **Disable the harness's own `sessions.db` writes** (`Agent(persist_session=False)`) so we don't double-persist; the website store becomes the *single* record — both the UI-canonical history and the source we replay into the model for multi-turn continuity (see §2). This decouples us from harness transcript lossiness and from any future harness session-format change, and keeps conversation data outside the agent's `run_sql` reach.

---

## 0.5 Architectural segregation (HARD CONSTRAINT)

Penny is two domains that **must never commingle**, and this feature sits squarely in one of them:

- **Agent domain** — what the LLM uses to do finance work: `backend/penny/tools/` (the `@tool` wrappers + `tools/_services/`), `backend/.agent/skills/`, `backend/penny/agent_factory.py`, `backend/penny/prompts.py`, and the prompts. It operates on the *finance* data (`derived_transactions`, `categories`, …), notably via the unrestricted `run_sql` tool.
- **Website domain** — the application that hosts the agent and owns user-facing CRUD: the FastAPI app (`backend/penny/api/`), account management, settings, and **conversation/message persistence (this feature)**.

**Dependency rule (one-directional): Website → Agent only.** The website constructs and invokes the agent; the bridge is the seam — it *runs* the agent and translates its event stream. The agent domain must have **zero** imports of conversation-persistence code, and the persistence code must not import agent tools/skills internals. Conversation persistence is **website-owned**, not agent infrastructure.

This forces three concrete departures from the naive plan:

1. **Do not put conversation models/CRUD in the shared `penny/adapters/db` facade.** That facade and `models.py` are imported throughout the agent domain (verified: `tools/transactions.py`, `tools/analytics.py`'s `run_sql`, `tools/_services/{persister,sync_service,split,refund,migrator,…}`, the Amazon plugin). Adding conversation tables/methods there commingles website CRUD into a module the agent links against. Instead, give the website its **own** persistence package with its **own** SQLAlchemy `Base`, models, and store/engine (e.g. `backend/penny/api/persistence/{models,store,engine}.py` — or a sibling `backend/penny/web/` package if you prefer the name explicit). The shared `adapters/db` layer stays finance-only.
2. **Keep conversation data out of the agent's `run_sql` blast radius.** `run_sql` (`tools/analytics.py` → `get_db().execute_raw_sql`) is intentionally unrestricted read+write over the finance DB. If conversation rows live in that same database, the agent can read or mutate a user's stored chat history as a side effect of answering a finance question — a segregation and privacy leak. **Store conversations in a separate database/schema from the finance data**, owned by the website's own engine: a dedicated Neon **schema** (e.g. `web.conversations`) with `run_sql`'s role/`search_path` scoped to the finance schema, or a separate SQLite file in dev (`penny_web.db`) — mirroring the harness's existing "`sessions.db` is separate" precedent. Defense-in-depth: even with separation, scope `run_sql` to the finance schema explicitly.
3. **The bridge is the only shared touchpoint — and that's allowed, because it is website code.** `api/bridge.py` already lives in the website domain; it runs the agent and sees its frames, so capturing persistence there does not violate the rule (website→agent). What must *not* happen: a tool or skill importing the persistence store to "log itself," or the persistence layer reaching into `tools/_services` for serialization helpers (it shares part-shapes with `api/bridge.py`'s `_translate`, which is website-internal — keep those helpers in the website domain).

A lint/test guardrail enforces this (see §5): assert nothing under `penny/tools` or the skills tree imports the persistence package, and that the persistence package imports neither `penny/tools` nor `penny/agent_factory`.

---

## 1. Data model

Add two tables — `conversations` and `conversation_messages` — to the **website-owned persistence package** on its own SQLAlchemy `Base` (per §0.5: `backend/penny/api/persistence/models.py`, **not** the shared `penny/adapters/db/models.py`). Use a **per-message `parts` JSON column** (a JSON array of part objects), not a separate polymorphic `parts` table.

### Justification: JSON parts column vs. polymorphic parts table vs. typed columns

- **Typed columns** (one column per part attribute) is rejected outright: parts are a heterogeneous union (text/reasoning/tool-call/tool-output/error/step markers) with wildly different shapes; this forces a sparse mega-row or many nullable columns.
- **Separate polymorphic `parts` table** (`type` discriminator + JSON payload + `ord`) is the textbook normalized choice and is defensible. But: (a) the AI SDK UIMessage is itself `{id, role, parts: [...]}` — the natural read/write unit is the whole message with its ordered parts; (b) we never query *across* parts (no "find all tool-call parts" analytics requirement); (c) ordering within a message is just array index — no need for an `ord` column and join; (d) one row per message keeps writes atomic and hydration a trivial `SELECT ... ORDER BY seq`. The cost is that we can't index into individual parts in SQL, which we don't need.
- **Chosen: `parts` as a JSON array on the message row.** Each element is a self-describing part object whose shape mirrors exactly what the bridge emits / what `useChat` expects, so hydration is near-passthrough. SQLAlchemy `JSON` type maps to native `JSONB`-equivalent on Postgres (use `JSON` for portability; optionally `JSONB` via `postgresql.JSONB().with_variant`) and to `TEXT`-backed JSON on SQLite — both already in use conceptually (the codebase stores JSON-as-TEXT in `categories.rules`).

### `conversations`

| column | type | notes |
|---|---|---|
| `conversation_id` | `String` PK | The client-generated UUID (today's `sessionId`). Reuse it verbatim so it stays 1:1 with the harness `sessions.db` `session_id`. |
| `title` | `String` nullable | Null until titled (see §3 titling). |
| `created_at` | `TIMESTAMP` server_default `CURRENT_TIMESTAMP` | |
| `updated_at` | `TIMESTAMP` server_default `CURRENT_TIMESTAMP` | Bumped on each new message; the ordering key for the conversation list (doubles as "last activity"). |

(No `user_id` yet — single-user app today; note it as the trigger for a future additive migration. There is no `accounts` table and no `account_id` FK in this rollout either; `account_id` is a future additive column on `conversations`, added when the product grows a notion of per-account conversations.)

### `conversation_messages`

| column | type | notes |
|---|---|---|
| `message_id` | `Integer` PK autoincrement | Surrogate. |
| `conversation_id` | `String` FK→`conversations.conversation_id` `ondelete=CASCADE`, indexed | |
| `ai_sdk_message_id` | `String` nullable, unique-per-conversation | The Vercel AI SDK (`useChat`) `messageId` — `run_id` for assistant turns, the client-minted UUID for user turns. Named for its source so it's unambiguous which "client" it refers to. Used for idempotent upsert and to dedupe streaming-vs-final. |
| `seq` | `Integer` not null | Monotonic per conversation (mirrors the harness `ord` pattern in `sqlite.py`). Deterministic ordering without relying on PK. |
| `role` | `String` not null | `user` / `assistant`. (We do **not** create a `tool`-role row — tool output is folded into the owning assistant message's parts, matching `useChat`/`messages_to_ui` semantics.) |
| `parts` | `JSON` not null | Ordered array of part objects (see enumeration below). |
| `status` | `String` not null, default `'complete'` | `streaming` / `complete` / `error`. Drives reconciliation (§2). A turn that aborts (client disconnect / generator close) is recorded as `error`, not a separate `aborted` value — the UI treats both identically (truncated-but-coherent message) so the extra enum value earned nothing. CHECK constraint enumerating the three values (follow the existing `CheckConstraint` convention in `models.py`, mirrored into a future migration only if/when alembic is adopted). |
| `created_at` / `updated_at` | `TIMESTAMP` | |

Indexes: `Index("ix_conv_messages_conv_seq", "conversation_id", "seq")`; unique `Index("uq_conv_messages_ai_sdk_id", "conversation_id", "ai_sdk_message_id", unique=True)` (guard `ai_sdk_message_id IS NOT NULL` via `sqlite_where`/`postgresql_where`, matching the `uq_categories_key_active` partial-index pattern already in `models.py`).

### Every part type that must round-trip

The `parts` array stores objects shaped to match the AI SDK frames the bridge already emits (`bridge.py::_translate`) so hydration is symmetric. Enumerate them, each mapped to its originating bridge frame:

1. **User text** — `{type: "text", text}`. (From the inbound POST body, not a frame.)
2. **Assistant text** — `{type: "text", text, state: "done"}`. Reconciled from `text-start`/`text-delta`/`text-end` (frames keyed `t_<message_id>`).
3. **Reasoning / thinking summary** — `{type: "reasoning", text, state: "done"}`. From `reasoning-start`/`reasoning-delta`/`reasoning-end` (keyed `r_<message_id>`). This is what `9dac604` needed; here it round-trips natively.
4. **Tool-call invocation** — `{type: "tool-<name>", toolCallId, state: "input-available", input}`. From `tool-input-available` (`ToolCallEnd`: `tool_name` + `arguments`).
5. **Tool result (structured_content / MCP output)** — promote the matching tool-call part to `{type: "tool-<name>", toolCallId, state: "output-available", input, output}`. From `tool-output-available` (`ToolExecEnd` → `_serialize_tool_output`, which is `structured_content` verbatim or the MCP content envelope). **This is the high-fidelity payload the harness transcript loses.**
6. **Tool-output error** — promote the tool-call part to `{type: "tool-<name>", toolCallId, state: "output-error", errorText, input}`. From `tool-output-error` (`ToolExecEnd` with `event.error` or `result.error`).
7. **Stream-level error** — `{type: "error", errorText}` (a standalone part; the frontend `findStreamError` in `ChatScreen.tsx` already reads `parts[].type === "error"`). From the `error` frame (`Error` event, or a translation/loop failure synthesized by `stream_agent`).
8. **Step / finish markers** — `start`, `start-step`, `finish-step`, `finish` frames are stream-control, not content. **Do not store them as parts.** Their semantics are captured by the message `status` column (`complete` on `finish`) and by message boundaries. (If agent-ui later needs explicit `step-start` parts, they can be re-synthesized at hydration — see §3 — so we avoid persisting redundant control frames.)

**Streaming-vs-final reconciliation:** parts are stored in their *final* (`state: "done"` / `output-available`) form. Deltas are accumulated in memory during the turn (§2), not persisted per-delta. Ordering within `parts` follows first-appearance order of each part id across the frame stream (reasoning before text before tools, interleaved as the model emits them), which is exactly the order the bridge yields them — preserving the visual transcript order.

---

## 2. Capture: where and how to persist

**Capture at the bridge, accumulating into an in-memory message builder, flushing finalized messages to the website-owned conversation store (§0.5 — a separate DB/schema from the finance data, not `penny.db`'s finance tables).** Rationale:

- The bridge is the single point that sees every part at full fidelity (esp. `structured_content` and the error/`tool-output-error` distinction) — the harness transcript does not (§0).
- Capturing here means "what we persist" == "what we streamed" by construction, eliminating drift between live render and rehydrated render.
- We avoid re-deriving UI parts from the lossy harness transcript and avoid coupling to harness session internals.

### Mechanism

1. **New website-owned package** `backend/penny/api/persistence/` (per §0.5) with `models.py` (its own `Base`), `engine.py` (its own engine + `create_all`), and `store.py` exposing a `ConversationStore` over that **own** engine/session — *not* the shared finance `DB` facade. Mirror the repo's façade conventions (`session()` context manager, `expunge`) inside this store, but keep its SQLAlchemy self-contained so the agent domain never links to it.

2. **Persist the user message up front.** In `main.py::chat`, after extracting the prompt and before streaming, `ConversationStore.ensure_conversation(chat_id)` + `append_user_message(chat_id, ai_sdk_message_id, text)`. Doing it here (not in the bridge) guarantees the user turn is durable even if the client disconnects before any assistant frame.

3. **Wrap the frame stream with an accumulator.** Refactor `stream_agent` (or add `stream_and_persist`) so that as it yields each SSE frame it also feeds the frame to a `MessageAccumulator`:
   - `start` (`RunStart`) → open a new assistant message buffer keyed by `messageId` (= `run_id`), status `streaming`, **and insert the row immediately** with `parts=[]`, `status='streaming'`. This persists a placeholder before any content arrives so a page refresh mid-turn can show the in-flight assistant turn (and so an abort always has a row to finalize). The insert is an upsert keyed on `(conversation_id, ai_sdk_message_id)` so re-entry is idempotent.
   - `reasoning-*`, `text-*`, `tool-input-available`, `tool-output-available`/`-error`, `error` → update the buffer's parts (accumulate reasoning/text deltas by id; add/promote tool parts by `toolCallId`; append error parts).
   - `finish` (`RunEnd`) → finalize: set parts to `state: "done"`/`output-available`, status `complete`, and `upsert_assistant_message(...)` (keyed on `(conversation_id, ai_sdk_message_id)` so the `streaming` row is reconciled in place rather than duplicated). Bump `conversations.updated_at`.

   The accumulator logic is essentially the inverse of `_translate` and shares its id conventions (`t_`, `r_`, `toolCallId`); factor the id/state rules into small helpers so bridge and accumulator can't drift.

4. **Partial / aborted turns.** The `finally` block in `stream_agent` already awaits the runner and surfaces loop failures as an `error` frame. Extend it: on generator close / exception without a `finish`, flush whatever the buffer holds with `status='error'`, preserving partial reasoning/text/partial tool calls. Because parts are stored in final shape, an aborted turn simply has fewer parts and a non-`complete` status — hydration renders it as a truncated-but-coherent message. The flush is best-effort and must never raise into the (already-closed) response.

5. **Ordering & seq.** Allocate `seq` inside the facade insert under the session, using `COALESCE(MAX(seq),-1)+1` for the conversation (the proven pattern from harness `sqlite.py::_append_payloads`). User message gets seq N, the assistant turn gets seq N+1.

6. **Do not double-persist — disable the harness session writes.** Construct the agent with `persist_session=False` (the flag added to `agent-harness`'s `Agent`: the run loop still *reads* prior history from a supplied session but never *writes* messages or run-state to `sessions.db`). The website store becomes the **single** persistence layer — both the UI-canonical record and the source of model continuity. The reverse-map that makes this safe is a first-class component; see §6.

---

## 3. Hydration / replay and API surface

### Hydration (replace the lossy path outright)

Today `GET /api/sessions/{id}` reads the harness transcript via `messages_to_ui`. Switch it to read the new `conversation_messages` rows, which already hold UIMessage-shaped parts:

- New function `conversation_to_ui(rows) -> list[UIMessage]` in `hydration.py`: for each message row emit `{id: ai_sdk_message_id or f"hist_{seq}", role, parts}` — parts pass through nearly verbatim (they're already in UI shape). Because `structured_content` was stored faithfully at capture time, the `ThinkingBlock` special-case from `9dac604`, the `_parse_maybe_json` heuristic, and `_collect_tool_results` are all **dead** — no path needs them anymore, so **delete them** along with `messages_to_ui` itself.
- `conversation_to_ui` (reading `conversation_messages`) is the **only** hydration path. There is no runtime fallback to the lossy harness transcript: the website never reads `sessions.db` to reconstruct UI messages. Pre-feature conversations simply do not appear (see §4) — a clean break, acceptable because `persist_session=False` means new conversations live only in the app store going forward.
- If agent-ui requires explicit step markers for rendering, re-synthesize `start-step`/`finish-step` boundaries at hydration from message/role boundaries rather than persisting them (keeps the store clean).

### API surface (extend `backend/penny/api/main.py`)

This rollout ships exactly **one** persistence-facing endpoint and trims the rest:

- **Hydration (single conversation) — KEPT.** Repoint the existing `GET /api/sessions/{id}` to the faithful path: read `conversation_messages` rows and return `{sessionId, messages: conversation_to_ui(rows)}`. Response shape stays `{messages}`, so the frontend hydration `fetch` is untouched (zero frontend change). (Naming it `/api/sessions/{id}` is now a slight misnomer — it reads the conversation store, not the harness session — but keeping the path avoids a frontend edit; renaming to `/api/conversations/{id}` is a later cosmetic.)
- **Creation is lazy — no `POST /api/conversations`.** The frontend keeps sending `body.id` (its localStorage UUID) to `POST /api/chat`; the backend treats it as `conversation_id` and calls `ensure_conversation(id)` on the first chat. No create endpoint, no frontend "New chat" round-trip — "New chat" still just rolls a new local UUID.
- **No manual rename — no `PATCH /api/conversations/{id}`.** Titling is an internal write only: derive a title from the first user message (truncate) on the first assistant `finish`, written by the persistence layer (no extra model call, no endpoint). A future manual-rename or async LLM-titling job can add the endpoint then.

**Deferred (not built now):**

- `GET /api/conversations` (the conversation LIST) and any `preview`/`updated_at DESC` ordering — deferred with the sidebar below.
- **Frontend conversation sidebar.** No list UI, no server-side "New chat". The frontend is unchanged: it still hydrates one conversation via `GET /api/sessions/{id}` and mints local UUIDs. The sidebar + list endpoint land together in a later feature.

---

## 4. Schema creation / migration strategy (create_all-only, no alembic)

- **Additive tables only, on the website's own metadata.** `conversations` and `conversation_messages` are brand new and live on the website persistence package's **own** `Base` (§0.5). Create them via that package's own `create_all` (its own engine/schema), invoked from `bootstrap.py` alongside — but separate from — the finance `create_schema()`. On Neon use a dedicated `web` schema; in dev a separate SQLite file (`penny_web.db`). **No migration tooling required for the initial rollout** — additive only. Do **not** register them on the finance `Base.metadata`, or the agent's `run_sql` engine would see them.
- **JSON portability.** Use SQLAlchemy `JSON` (TEXT-backed on SQLite, native JSON on Postgres). Avoid Postgres-only types in the model so `create_all` works identically in dev SQLite and prod Neon. CHECK constraints declared in `__table_args__` are enforced by SQLite via the ORM and created by `create_all` on Postgres (no migration mirror needed *because there is no migration*; the facade comments about "must also be listed in the migration" pertain to the legacy alembic-on-main path and don't apply here).
- **Lean on Postgres TOAST compression (prod) for the JSON parts.** On Neon, large `parts` values are stored out-of-line and LZ-compressed automatically (TOAST) — SQL-result tables compress roughly 3–5×, base64 ~20–25% — so the on-disk footprint sits well below the logical JSON size with zero app-side work. This is the **primary storage lever** for the per-message JSON design; treat explicit per-part byte caps / artifact externalization as a later refinement, reached for only if a single part routinely exceeds the TOAST sweet spot (e.g. inline base64 chart images from `generate_chart`). **Dev caveat:** SQLite (`penny_web.db`) does **not** auto-compress, so local DB files look larger than prod — don't size prod from dev observations.
- **Pre-feature conversations do not carry over (clean break).** Conversations that only live in `sessions.db` are not imported — there is no backfill. This is acceptable: the lossy `messages_to_ui` reconstruction is being removed entirely, and going forward `persist_session=False` means new conversations live only in the app store anyway. Pre-feature `sessions.db` data is left untouched and simply unread.
- **When alembic becomes necessary** (called out explicitly): `create_all` only *creates missing* tables/columns — it never alters existing ones. The first time we need to **change** a shipped column (add `user_id` to `conversations` after data exists, change a type, add a NOT NULL with backfill, add a CHECK to a populated table, rename), `create_all` cannot do it and we must introduce alembic (or a hand-rolled idempotent DDL step in `bootstrap`). Recommendation: ship these additive tables now without alembic; adopt alembic at the first non-additive change, and migrate the whole schema under it then.

---

## 5. Critical files, trade-offs, risks, and commit sequence

### Files to change

- `backend/penny/api/persistence/models.py` *(new)* — `Conversation`, `ConversationMessage` on the website's **own** `Base` (+ indexes, CHECK on `status`). **Not** added to `penny/adapters/db/models.py`.
- `backend/penny/api/persistence/engine.py` *(new)* — the website store's engine + `create_all` against its separate DB/schema (§0.5).
- `backend/penny/api/persistence/store.py` *(new)* — `ConversationStore` over the website's own engine/session: `ensure_conversation`, `append_user_message`, `upsert_assistant_message`, `get_conversation_messages`, `set_conversation_title` (`session()` + `expunge` conventions; `seq` via `COALESCE(MAX(seq),-1)+1`). Self-contained SQLAlchemy — does **not** import the finance `DB` facade. (`list_conversations` is deferred with the LIST endpoint.)
- `backend/penny/api/persistence/rehydrate.py` *(new)* — the reverse-map (stored `parts` → harness `Message`s) that seeds model continuity once `persist_session=False`. See §6 below.
- `backend/penny/api/bridge.py` — add the `MessageAccumulator` and `stream_and_persist` wrapper (or fold persistence into `stream_agent`); factor shared id/state rules out of `_translate` (kept website-internal).
- `backend/penny/api/main.py` — `ensure_conversation` + `append_user_message` in `chat()`; new `GET/POST/PATCH /api/conversations[...]`; repoint hydration.
- `backend/penny/api/hydration.py` — add `conversation_to_ui`; **delete** `messages_to_ui` and its now-dead helpers (`_parse_maybe_json`, `_collect_tool_results`, the `ThinkingBlock` special-case).
- `backend/penny/bootstrap.py` — call the website store's `create_all` alongside (but separate from) the finance `create_schema()`.
- `backend/tests/test_domain_segregation.py` *(new)* — import-boundary guardrail (see Cross-dependencies below).

(Deferred: `run_sql` finance-schema scoping in `tools/analytics.py` — defense-in-depth beyond the separate DB; and `frontend/src/ChatScreen.tsx` — the conversation sidebar. Both ship with later features.)

### Key trade-offs

- **Capture at bridge vs. from transcript:** bridge wins on fidelity and live/replay parity; cost is the accumulator must mirror `_translate`'s id/state conventions (mitigated by shared helpers + a round-trip test that runs frames through `_translate` then the accumulator and asserts equality with `conversation_to_ui`).
- **JSON parts column vs. polymorphic table:** chose JSON for write-atomicity, near-passthrough hydration, and zero cross-part query needs; accept loss of in-SQL part indexing.
- **Penny-owned tables vs. extending harness session:** chose Penny-owned to decouple from harness lossiness and format churn; cost is two stores of overlapping data (model memory vs. UI record) — acceptable and intentional.
- **Separate website store vs. co-locating in the finance DB:** chose a separate DB/schema (§0.5) so the agent's `run_sql` cannot reach conversation data and so website CRUD never links the agent domain; cost is a second engine + its own `create_all` (and eventually its own alembic). Worth it — segregation is a hard constraint here, not a preference.

### Risks

- **Large tool payloads.** `structured_content` for SQL/chart tools can be large; storing verbatim per message could bloat rows. **The primary lever is Postgres TOAST** (§4): large `parts` values are stored out-of-line and LZ-compressed automatically in prod. An explicit per-part byte cap / truncation marker is **deferred** — reached for only if a single part routinely exceeds the TOAST sweet spot (e.g. inline base64 chart images). Until then the bridge's `default=str` "never kill the stream" behavior is the only guard, and the accumulator stores output verbatim.
- **PII + agent exfiltration of stored data.** Parts will contain real transaction amounts, merchants, and tool outputs. `email_receipts.subject/sender` PII rules say such fields must never surface in LLM responses — but tool *outputs* legitimately contain finance data the user is viewing. Two risks: at-rest exposure, and the agent reading its own past conversations back via `run_sql`. Mitigate by storing these rows in the website's separate schema/DB (§0.5) — reachable by the website, **outside the agent's `run_sql`**; never log `parts` payloads (the loguru file sink in `_logging` must not dump them); "delete conversation" must `CASCADE` (it does via FK) to truly remove the record.
- **Ordering / concurrency.** `seq` allocation under a transaction prevents races; the app is effectively single-writer per conversation today, but the `COALESCE(MAX)+1` approach + per-conversation uniqueness on `ai_sdk_message_id` keeps it safe.
- **Aborted-turn fidelity.** Client disconnect mid-stream must still flush a partial `aborted` row; ensure the flush path can't raise into the (already-closed) response and is covered by a test simulating early generator close.
- **Idempotent replay.** A client re-POST or reconnect with the same `messageId` must upsert, not duplicate — enforced by the per-conversation unique `ai_sdk_message_id`.

### Cross-dependencies (segregation watch-list)

Each of these is a place the agent and website domains could quietly recouple; the mitigation keeps the dependency one-directional (website→agent) or eliminates it.

- **Shared DB facade (`penny/adapters/db`) — sharpest risk.** Agent tools and `tools/_services/*` import it pervasively (`tools/transactions.py`, `tools/analytics.py`, `tools/_services/persister.py`, `…/sync_service.py`, etc.). Conversation persistence must NOT be added here. *Mitigation:* separate website persistence package with its own `Base`/engine (§0.5); a guardrail test forbids `penny/tools` → persistence imports.
- **`run_sql` over a single database.** `tools/analytics.py` runs arbitrary read+write SQL on the finance DB. If conversation tables share that DB, the agent can read or mutate chat history. *Mitigation:* separate schema/DB for the website store + scope `run_sql`'s role/`search_path` to the finance schema (§0.5).
- **The bridge (`api/bridge.py`).** Legitimately shared — it runs the agent and is the capture point — and allowed because the dependency is website→agent. *Watch:* keep the `MessageAccumulator`/`_translate` part-shaping helpers in the website domain; never let a tool import them.
- **Workspace / session id.** `chat_id`/`sessionId` is shared by *value* between the harness `sessions.db` (model memory) and the website store (UI record). That's an identifier, not a code dependency — fine. The persistence package **must not import `agent_harness.sessions` at all** (the lossy `messages_to_ui` read is removed), and must never implement the harness `Session` — the website reaches into harness session internals nowhere.
- **`bootstrap.py`.** Will trigger both the finance `create_schema()` and the website store's `create_all`. Keep them two distinct calls on two distinct metadatas so neither schema leaks into the other engine.
- **Frontend.** `ChatScreen.tsx` (website UI) talks only to website endpoints — no agent coupling. Noted for completeness.
- **Guardrail test (`tests/test_domain_segregation.py`).** Assert (a) no module under `penny/tools` or the skills tree imports `penny.api.persistence`, and (b) `penny.api.persistence` imports neither `penny.tools` nor `penny.agent_factory`. Make it fail the suite so a future accidental import is caught at CI time, not in review.

### Step-by-step commit sequence (small, reviewable)

This rollout is **six commits** (the LIST endpoint + sidebar and the manual-rename/`POST`/`PATCH` endpoints are trimmed; titling is folded into commit 3/5 as an internal write):

1. **`feat(web): conversation persistence package (models + own engine/schema)`** — `api/persistence/{models,engine}.py` on its own `Base`; its `create_all` wired into `bootstrap` as a separate schema/DB (§0.5). Ship the guardrail `tests/test_domain_segregation.py` in this same commit, plus a unit test that the tables build and that the finance `Base.metadata` does **not** include them.
2. **`feat(web): ConversationStore`** — `api/persistence/store.py`: `ensure_conversation`, `append_user_message`, `upsert_assistant_message`, `get_conversation_messages`, `set_conversation_title`, with unit tests (seq monotonicity, upsert idempotency). Imports neither the finance facade nor any agent module.
3. **`feat(api): MessageAccumulator + persist turns at the bridge`** — accumulator + `stream_and_persist`; insert the `streaming` row on `RunStart`, finalize on `RunEnd`, record `error` on stream error / abort. Round-trip test (frames → accumulator → `conversation_to_ui` == streamed parts), including `tool-output-error` and stream `error`.
4. **`feat(api): persist user message + finalize/abort in /api/chat`** — lazy `ensure_conversation` + `append_user_message`; best-effort abort flush (status `error`) that can't raise into the closed response.
5. **`feat(api): conversation_to_ui hydration; delete messages_to_ui`** — switch hydration to the faithful path and **delete** `messages_to_ui` and its now-dead helpers; `conversation_to_ui` is the sole hydration path; repoint `GET /api/sessions/{id}`; hydration tests covering all part types (build on `9dac604`'s reasoning test).
6. **`feat(api): seed agent from app store + persist_session=False`** — the DEEPENED reverse-map (§6): `api/persistence/rehydrate.py` maps stored `parts` → harness `Message`s, `main.py` seeds them into the agent on each `/api/chat`, **then** flips `Agent(persist_session=False)`. Gated by the continuity round-trip test (§6). If the continuity test can't be made green, `persist_session` stays at its default `True` and the flip is NOT made.

**Deferred (later features, not this rollout):** conversation LIST (`GET /api/conversations`) + the frontend sidebar; manual rename / `POST` / `PATCH` endpoints; per-part byte cap; the alembic adoption at the first non-additive change.

---

## 6. Model continuity: the stored-`parts` → harness-`Message` reverse-map (DEEPENED)

This is the load-bearing component that lets us collapse to **one** store. Once `Agent(persist_session=False)` stops `sessions.db` from accumulating, the model no longer remembers prior turns on its own. On every `POST /api/chat` the website must reconstruct prior-turn context **from the app store** and seed it into the run, so the model *sees* the earlier conversation — not merely so the UI re-renders it.

### Why its own module (`api/persistence/rehydrate.py`)

The reverse-map is the inverse of **two** forward maps and should not be buried in either:

1. It inverts `bridge.py::_translate` / the accumulator: stored UI `parts` (`{type:"text"|"reasoning"|"tool-<name>"|"error", …}`) are exactly what `_translate` produced from harness events.
2. It inverts the harness `Message` serialization (`agent_harness.core.models`): the *target* is a `list[Message]` whose `content` blocks are `TextBlock` / `ThinkingBlock` / `ToolCallBlock` / `ToolResultBlock` — the same shapes the loop appends to `rc.messages` and feeds the model.

Keeping it in the website domain (it imports `agent_harness.core.models`, which is a model-boundary type, **not** an agent tool/skill — so it does not violate segregation) and giving it a dedicated module makes the symmetry reviewable and the unit testable in isolation.

### The mapping (`conversation_messages` rows → `list[Message]`)

For each stored message row, in `seq` order, emit harness `Message`s:

- **User row** (`role="user"`, text parts) → one `Message(role="user", content=[TextBlock(text=…)])`.
- **Assistant row** → split its `parts` into the harness's *two-message* shape, because the harness models a tool round-trip as an assistant message carrying `ToolCallBlock`s **followed by** a separate `role="tool"` message carrying the matching `ToolResultBlock`s (see `loop.py::ToolDispatch`):
  - `{type:"reasoning", text}` → `ThinkingBlock(text)` on the assistant message (leading, mirroring how the model emits thinking before content).
  - `{type:"text", text}` → `TextBlock(text)` on the assistant message.
  - `{type:"tool-<name>", toolCallId, input, output|errorText, state}` → a `ToolCallBlock(id=toolCallId, name=<name>, arguments=input)` on the assistant message, **paired** with a `ToolResultBlock(tool_call_id=toolCallId, content=…)` collected into the trailing `role="tool"` message. The tool **name** is recovered by stripping the `tool-` prefix from the part `type` (the same convention `_translate` used to build it).
  - **`output-error` parts** map back to a model-visible tool message too: the `ToolResultBlock.content` is set to the `errorText` (a short `"Error: <errorText>"` string), so the model sees that the tool failed rather than silently losing the turn. This matches `loop.py`, where a failed tool still produces a `ToolResultBlock` (via `content_to_text`).
  - `{type:"error"}` (stream-level error) parts are **dropped** from the model seed — they are a UI artifact (a red banner), not conversational content the model should condition on.
  - Tool-call↔result pairing is by `toolCallId`; the assistant `ToolCallBlock`s preserve part order, and the single trailing `tool` message carries all results for that assistant turn in the same order (one assistant turn → at most one following tool message, matching the loop's batching).

`structured_content` outputs are serialized back to the `ToolResultBlock.content` string with `content_to_text`-equivalent JSON dumping — fidelity to the *model* only needs the textual content the loop itself would have stored, not the rich UI payload (the UI payload lives in the stored part and is what hydration replays to the browser).

### Seeding into the agent

Reuse the harness's own continuity path rather than fighting it: build an `InMemorySession(session_id=conversation_id)`, `add_messages(reverse_mapped_prior_messages)`, and pass it as the agent's `session`. With `persist_session=False`, `PrepareTurn` (loop.py) does exactly the right thing on turn 0: it loads the seeded prior messages from the session (`agent.session.get_messages()` when `rc.turn == 0 and not rc.messages`), inserts the system instructions, appends the **new** user prompt, and — because `persist_session=False` — never writes any of it back to `sessions.db`. No duplicate user turn, no second store. The new user turn and assistant turn are persisted to the **app store** by the bridge/`/api/chat` paths from commits 3–4, which already own that write.

### The continuity round-trip test (the gate)

The test must assert continuity *into the model*, not just UI re-render:

1. Turn 1: run the agent against a `FakeModel` (harness test fake) that emits a tool call + text; capture the streamed frames; persist them through the accumulator (commit 3) into a `ConversationStore` (tmp SQLite).
2. Turn 2: build a fresh agent with `persist_session=False`, seed it from the app store via `rehydrate` + `InMemorySession`, and run a new prompt against a `FakeModel` that **records the `messages` list it is handed**. Assert that list contains turn 1's user text, the assistant `ToolCallBlock`, the `ToolResultBlock`, and the assistant text — i.e. the model can see the earlier tool-call turn — followed by turn 2's new user message.

Covering a **tool-call** turn (not just plain text) is required because the assistant/tool message split is where the reverse-map is easiest to get wrong. **If this test cannot be made green, leave `persist_session=True` and do not flip the flag** — an un-seeded `persist_session=False` silently breaks multi-turn memory in the live app.

---

## Critical files for implementation

- `backend/penny/api/bridge.py`
- `backend/penny/api/persistence/` (new: `models.py` on its own `Base`, `engine.py`, `store.py`, `rehydrate.py`)
- `backend/penny/api/main.py`
- `backend/penny/api/hydration.py`
- `backend/penny/bootstrap.py` (separate `create_all` for the website store)
