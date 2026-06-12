# Implementation Plan: Persisting Chat Conversations and Messages

## 0. Context discovered (verified against code)

- **Entry point** `backend/penny/api/main.py`: `POST /api/chat` builds a per-request `Agent` bound to a per-`chat_id` `SqliteSession` (harness `sessions.db` in the workspace, separate from `penny.db`), then streams via `stream_agent(agent, prompt)`. `GET /api/sessions/{id}` hydrates by reading `session.get_messages()` and passing through `messages_to_ui`.
- **Bridge** `backend/penny/api/bridge.py`: subscribes to the harness `InMemoryEventBus`, runs the agent, and maps each `Event` to one or more AI SDK UI-message-stream frames. This is the only place that sees the full fidelity of every part — notably `ToolExecEnd.result.structured_content` (emitted verbatim via `_serialize_tool_output`) and the `tool-output-error` distinction.
- **Harness already persists a transcript** to `sessions.db` incrementally inside the loop (`agent_harness/core/loop.py`): user `Message` at `PrepareTurn`, each assistant `final_message`, each `tool_msg`. So conversation continuity for the *model* already survives restarts.
- **Critical gap (the reason to persist ourselves):** the harness transcript is **lossy for the UI**. `ToolResultBlock.content` is `content_to_text(result)` — a flat string. The rich `structured_content` (chart specs, SQL result tables, MCP structured output) that the bridge sends to the browser is **not stored**. Today's `messages_to_ui` (`backend/penny/api/hydration.py`) recovers tool output only by `json.loads`-ing that string — it round-trips by accident when a tool happened to emit JSON-as-text, and silently degrades otherwise. Stream-level `Error` frames and the `tool-output-error` vs `tool-output-available` distinction are also **absent** from the transcript. Commit `9dac604` patched one symptom of this lossiness (thinking summaries were dropped) by special-casing `ThinkingBlock`; we should stop patching the lossy path and instead capture the UI-faithful frame stream.
- **Schema reality** `backend/penny/bootstrap.py` calls `db.create_schema()` → `Base.metadata.create_all(engine)` on startup. **No alembic** (despite stale references in facade docstrings). New tables are purely additive, so `create_all` picks them up for free on both SQLite (`penny.db`) and Neon Postgres.
- **Frontend** `frontend/src/ChatScreen.tsx`: `sessionId` is a `crypto.randomUUID()` persisted in `localStorage` under `penny:sessionId`; "New chat" just rolls a new UUID and reloads. It already hydrates from `GET /api/sessions/{id}` before mounting `useChat`. There is **no conversation list** and no titling.

**Design stance:** Persist Penny's own UI-faithful record captured **at the bridge** as frames stream, in a **website-owned, agent-isolated** store (see §0.5) — *not* the shared finance DB/facade. Treat the harness `sessions.db` as the model's working memory (leave it as-is for model continuity); treat the new tables as the website's canonical record for the UI. This decouples us from harness transcript lossiness and from any future harness session-format change, and keeps conversation data outside the agent's `run_sql` reach.

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
| `updated_at` | `TIMESTAMP` server_default `CURRENT_TIMESTAMP` | Bumped on each new message; ordering key for the conversation list. |
| `last_message_at` | `TIMESTAMP` nullable | Convenience for list sorting/preview. |

(No `user_id` yet — single-user app today. Add the column nullable now if multi-user is on the near horizon; otherwise note it as the trigger for a future additive migration.)

### `conversation_messages`

| column | type | notes |
|---|---|---|
| `message_id` | `Integer` PK autoincrement | Surrogate. |
| `conversation_id` | `String` FK→`conversations.conversation_id` `ondelete=CASCADE`, indexed | |
| `client_message_id` | `String` nullable, unique-per-conversation | The AI SDK `messageId` (`run_id` for assistant turns, the client UUID for user turns). Used for idempotent upsert and to dedupe streaming-vs-final. |
| `seq` | `Integer` not null | Monotonic per conversation (mirrors the harness `ord` pattern in `sqlite.py`). Deterministic ordering without relying on PK. |
| `role` | `String` not null | `user` / `assistant`. (We do **not** create a `tool`-role row — tool output is folded into the owning assistant message's parts, matching `useChat`/`messages_to_ui` semantics.) |
| `parts` | `JSON` not null | Ordered array of part objects (see enumeration below). |
| `status` | `String` not null, default `'complete'` | `streaming` / `complete` / `aborted` / `error`. Drives reconciliation (§2). CHECK constraint enumerating the four values (follow the existing `CheckConstraint` convention in `models.py`, mirrored into a future migration only if/when alembic is adopted). |
| `created_at` / `updated_at` | `TIMESTAMP` | |

Indexes: `Index("ix_conv_messages_conv_seq", "conversation_id", "seq")`; unique `Index("uq_conv_messages_client_id", "conversation_id", "client_message_id", unique=True)` (guard `client_message_id IS NOT NULL` via `sqlite_where`/`postgresql_where`, matching the `uq_categories_key_active` partial-index pattern already in `models.py`).

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

2. **Persist the user message up front.** In `main.py::chat`, after extracting the prompt and before streaming, `ConversationStore.ensure_conversation(chat_id)` + `append_user_message(chat_id, client_message_id, text)`. Doing it here (not in the bridge) guarantees the user turn is durable even if the client disconnects before any assistant frame.

3. **Wrap the frame stream with an accumulator.** Refactor `stream_agent` (or add `stream_and_persist`) so that as it yields each SSE frame it also feeds the frame to a `MessageAccumulator`:
   - `start` (`RunStart`) → open a new assistant message buffer keyed by `messageId` (= `run_id`), status `streaming`. Optionally insert a `streaming`-status row immediately (enables "resume after refresh mid-turn"); simpler v1: buffer in memory and insert on first finalized content.
   - `reasoning-*`, `text-*`, `tool-input-available`, `tool-output-available`/`-error`, `error` → update the buffer's parts (accumulate reasoning/text deltas by id; add/promote tool parts by `toolCallId`; append error parts).
   - `finish` (`RunEnd`) → finalize: set parts to `state: "done"`/`output-available`, status `complete`, and `upsert_assistant_message(...)` (keyed on `(conversation_id, client_message_id)` so a retry/replay is idempotent). Bump `conversations.updated_at`/`last_message_at`.

   The accumulator logic is essentially the inverse of `_translate` and shares its id conventions (`t_`, `r_`, `toolCallId`); factor the id/state rules into small helpers so bridge and accumulator can't drift.

4. **Partial / aborted turns.** The `finally` block in `stream_agent` already awaits the runner and surfaces loop failures as an `error` frame. Extend it: on generator close / exception without a `finish`, flush whatever the buffer holds with `status='aborted'` (or `'error'` if an `error` frame was seen), preserving partial reasoning/text/partial tool calls. Because parts are stored in final shape, an aborted turn simply has fewer parts and a non-`complete` status — hydration renders it as a truncated-but-coherent message. Use `BackgroundTask` on the `StreamingResponse` or a `finally` flush; ensure the flush is best-effort and never raises into the response.

5. **Ordering & seq.** Allocate `seq` inside the facade insert under the session, using `COALESCE(MAX(seq),-1)+1` for the conversation (the proven pattern from harness `sqlite.py::_append_payloads`). User message gets seq N, the assistant turn gets seq N+1.

6. **Do not double-persist.** We leave the harness session writes (`sessions.db`) untouched — they remain the model's context for multi-turn continuity. Our tables are UI-canonical only.

---

## 3. Hydration / replay and API surface

### Hydration (reuse/extend, then supersede the lossy path)

Today `GET /api/sessions/{id}` reads the harness transcript via `messages_to_ui`. Switch it to read the new `conversation_messages` rows, which already hold UIMessage-shaped parts:

- New function `conversation_to_ui(rows) -> list[UIMessage]` in `hydration.py`: for each message row emit `{id: client_message_id or f"hist_{seq}", role, parts}` — parts pass through nearly verbatim (they're already in UI shape). This makes the `ThinkingBlock` special-case from `9dac604`, the `_parse_maybe_json` heuristic, and `_collect_tool_results` all unnecessary for the new path, because `structured_content` was stored faithfully at capture time.
- Keep `messages_to_ui` as a **fallback** for conversations that predate the feature (rows absent in `conversation_messages` but present in `sessions.db`) — and as a one-time backfill source (§4). This is the build-on-`9dac604` move: that commit fixed thinking replay in the lossy path; we keep that path working for legacy sessions while routing new sessions through the faithful path.
- If agent-ui requires explicit step markers for rendering, re-synthesize `start-step`/`finish-step` boundaries at hydration from message/role boundaries rather than persisting them (keeps the store clean).

### API surface (extend `backend/penny/api/main.py`)

- `GET /api/conversations` → `[{conversationId, title, createdAt, updatedAt, lastMessageAt, preview}]` ordered by `updated_at DESC`. (`preview` = first ~80 chars of the first user text part.)
- `GET /api/conversations/{id}` → `{conversationId, title, messages: conversation_to_ui(rows)}`. (Either rename `GET /api/sessions/{id}` to this or keep `/api/sessions/{id}` as an alias to avoid touching the frontend hydration call in one step.)
- `POST /api/conversations` → create an empty conversation, return its id. Lets the frontend "New chat" create server-side rather than only minting a localStorage UUID.
- `PATCH /api/conversations/{id}` → set `title`. **Titling:** v1 derive from the first user message (truncate) on first assistant `finish`, written by the persistence layer (no extra model call); leave an explicit `PATCH` for manual rename and a hook for an async LLM-titling job later.
- **Conversation id propagation:** unchanged contract — the frontend keeps sending `body.id` (the UUID) to `POST /api/chat`; the backend treats it as `conversation_id`. So `chat()` already receives the id; we just `ensure_conversation` on it.

### Frontend (`frontend/src/ChatScreen.tsx`)

- Point hydration at `GET /api/conversations/{id}` (or keep `/api/sessions/{id}`); response shape is compatible (`{messages}`).
- Add a conversation sidebar/list fed by `GET /api/conversations`; "New chat" calls `POST /api/conversations` (or keeps the local-UUID approach and lets the backend lazily `ensure_conversation` on first send — the lazy path needs zero frontend change and is the smaller first commit).

---

## 4. Schema creation / migration strategy (create_all-only, no alembic)

- **Additive tables only, on the website's own metadata.** `conversations` and `conversation_messages` are brand new and live on the website persistence package's **own** `Base` (§0.5). Create them via that package's own `create_all` (its own engine/schema), invoked from `bootstrap.py` alongside — but separate from — the finance `create_schema()`. On Neon use a dedicated `web` schema; in dev a separate SQLite file (`penny_web.db`). **No migration tooling required for the initial rollout** — additive only. Do **not** register them on the finance `Base.metadata`, or the agent's `run_sql` engine would see them.
- **JSON portability.** Use SQLAlchemy `JSON` (TEXT-backed on SQLite, native JSON on Postgres). Avoid Postgres-only types in the model so `create_all` works identically in dev SQLite and prod Neon. CHECK constraints declared in `__table_args__` are enforced by SQLite via the ORM and created by `create_all` on Postgres (no migration mirror needed *because there is no migration*; the facade comments about "must also be listed in the migration" pertain to the legacy alembic-on-main path and don't apply here).
- **Backfill (optional, idempotent).** For pre-existing conversations that only live in `sessions.db`: a one-shot script `backend/scripts/backfill_conversations.py` that, per `session_id`, reads `session.get_messages()`, runs the *legacy* `messages_to_ui`, and inserts `conversation_messages` rows if none exist. Lossy for old tool outputs (that data is already gone), but recovers text/reasoning/tool-call structure. Gate with "skip if conversation already has rows."
- **When alembic becomes necessary** (called out explicitly): `create_all` only *creates missing* tables/columns — it never alters existing ones. The first time we need to **change** a shipped column (add `user_id` to `conversations` after data exists, change a type, add a NOT NULL with backfill, add a CHECK to a populated table, rename), `create_all` cannot do it and we must introduce alembic (or a hand-rolled idempotent DDL step in `bootstrap`). Recommendation: ship these additive tables now without alembic; adopt alembic at the first non-additive change, and migrate the whole schema under it then.

---

## 5. Critical files, trade-offs, risks, and commit sequence

### Files to change

- `backend/penny/api/persistence/models.py` *(new)* — `Conversation`, `ConversationMessage` on the website's **own** `Base` (+ indexes, CHECK on `status`). **Not** added to `penny/adapters/db/models.py`.
- `backend/penny/api/persistence/engine.py` *(new)* — the website store's engine + `create_all` against its separate DB/schema (§0.5).
- `backend/penny/api/persistence/store.py` *(new)* — `ConversationStore` over the website's own engine/session: `ensure_conversation`, `append_user_message`, `upsert_assistant_message`, `list_conversations`, `get_conversation_messages`, `set_conversation_title` (`session()` + `expunge` conventions; `seq` via `COALESCE(MAX(seq),-1)+1`). Self-contained SQLAlchemy — does **not** import the finance `DB` facade.
- `backend/penny/api/bridge.py` — add the `MessageAccumulator` and `stream_and_persist` wrapper (or fold persistence into `stream_agent`); factor shared id/state rules out of `_translate` (kept website-internal).
- `backend/penny/api/main.py` — `ensure_conversation` + `append_user_message` in `chat()`; new `GET/POST/PATCH /api/conversations[...]`; repoint hydration.
- `backend/penny/api/hydration.py` — add `conversation_to_ui`; keep `messages_to_ui` as legacy/backfill.
- `backend/penny/bootstrap.py` — call the website store's `create_all` alongside (but separate from) the finance `create_schema()`.
- `backend/penny/tools/analytics.py` (`run_sql`) — scope to the finance schema so it cannot reach the website store (defense-in-depth; §0.5).
- `frontend/src/ChatScreen.tsx` — (later commit) conversation list + repointed hydration.
- `backend/scripts/backfill_conversations.py` *(new, optional)*.
- `backend/tests/test_domain_segregation.py` *(new)* — import-boundary guardrail (see Cross-dependencies below).

### Key trade-offs

- **Capture at bridge vs. from transcript:** bridge wins on fidelity and live/replay parity; cost is the accumulator must mirror `_translate`'s id/state conventions (mitigated by shared helpers + a round-trip test that runs frames through `_translate` then the accumulator and asserts equality with `conversation_to_ui`).
- **JSON parts column vs. polymorphic table:** chose JSON for write-atomicity, near-passthrough hydration, and zero cross-part query needs; accept loss of in-SQL part indexing.
- **Penny-owned tables vs. extending harness session:** chose Penny-owned to decouple from harness lossiness and format churn; cost is two stores of overlapping data (model memory vs. UI record) — acceptable and intentional.
- **Separate website store vs. co-locating in the finance DB:** chose a separate DB/schema (§0.5) so the agent's `run_sql` cannot reach conversation data and so website CRUD never links the agent domain; cost is a second engine + its own `create_all` (and eventually its own alembic). Worth it — segregation is a hard constraint here, not a preference.

### Risks

- **Large tool payloads.** `structured_content` for SQL/chart tools can be large; storing verbatim per message could bloat rows. Mitigate: cap stored `output` size (e.g., truncate/elide with a `truncated: true` marker beyond N KB), matching the bridge's `default=str` "never kill the stream" philosophy. Default ~256 KB/part.
- **PII + agent exfiltration of stored data.** Parts will contain real transaction amounts, merchants, and tool outputs. `email_receipts.subject/sender` PII rules say such fields must never surface in LLM responses — but tool *outputs* legitimately contain finance data the user is viewing. Two risks: at-rest exposure, and the agent reading its own past conversations back via `run_sql`. Mitigate by storing these rows in the website's separate schema/DB (§0.5) — reachable by the website, **outside the agent's `run_sql`**; never log `parts` payloads (the loguru file sink in `_logging` must not dump them); "delete conversation" must `CASCADE` (it does via FK) to truly remove the record.
- **Ordering / concurrency.** `seq` allocation under a transaction prevents races; the app is effectively single-writer per conversation today, but the `COALESCE(MAX)+1` approach + per-conversation uniqueness on `client_message_id` keeps it safe.
- **Aborted-turn fidelity.** Client disconnect mid-stream must still flush a partial `aborted` row; ensure the flush path can't raise into the (already-closed) response and is covered by a test simulating early generator close.
- **Idempotent replay.** A client re-POST or reconnect with the same `messageId` must upsert, not duplicate — enforced by the per-conversation unique `client_message_id`.

### Cross-dependencies (segregation watch-list)

Each of these is a place the agent and website domains could quietly recouple; the mitigation keeps the dependency one-directional (website→agent) or eliminates it.

- **Shared DB facade (`penny/adapters/db`) — sharpest risk.** Agent tools and `tools/_services/*` import it pervasively (`tools/transactions.py`, `tools/analytics.py`, `tools/_services/persister.py`, `…/sync_service.py`, etc.). Conversation persistence must NOT be added here. *Mitigation:* separate website persistence package with its own `Base`/engine (§0.5); a guardrail test forbids `penny/tools` → persistence imports.
- **`run_sql` over a single database.** `tools/analytics.py` runs arbitrary read+write SQL on the finance DB. If conversation tables share that DB, the agent can read or mutate chat history. *Mitigation:* separate schema/DB for the website store + scope `run_sql`'s role/`search_path` to the finance schema (§0.5).
- **The bridge (`api/bridge.py`).** Legitimately shared — it runs the agent and is the capture point — and allowed because the dependency is website→agent. *Watch:* keep the `MessageAccumulator`/`_translate` part-shaping helpers in the website domain; never let a tool import them.
- **Workspace / session id.** `chat_id`/`sessionId` is shared by *value* between the harness `sessions.db` (model memory) and the website store (UI record). That's an identifier, not a code dependency — fine. Keep the legacy harness-transcript read (`messages_to_ui`, used for fallback/backfill) as the *only* place the website reaches into harness session internals.
- **`bootstrap.py`.** Will trigger both the finance `create_schema()` and the website store's `create_all`. Keep them two distinct calls on two distinct metadatas so neither schema leaks into the other engine.
- **Frontend.** `ChatScreen.tsx` (website UI) talks only to website endpoints — no agent coupling. Noted for completeness.
- **Guardrail test (`tests/test_domain_segregation.py`).** Assert (a) no module under `penny/tools` or the skills tree imports `penny.api.persistence`, and (b) `penny.api.persistence` imports neither `penny.tools` nor `penny.agent_factory`. Make it fail the suite so a future accidental import is caught at CI time, not in review.

### Step-by-step commit sequence (small, reviewable)

1. **`feat(web): conversation persistence package (models + own engine/schema)`** — `api/persistence/{models,engine}.py` on its own `Base`; its `create_all` wired into `bootstrap` as a separate schema/DB (§0.5). Ship the guardrail `tests/test_domain_segregation.py` in this same commit, plus a unit test that the tables build and that the finance `Base.metadata` does **not** include them.
2. **`feat(web): ConversationStore`** — `api/persistence/store.py`: `ensure_conversation`, `append_user_message`, `upsert_assistant_message`, `list/get/set_title`, with unit tests (seq monotonicity, upsert idempotency). Imports neither the finance facade nor any agent module.
3. **`feat(api): MessageAccumulator + persist assistant turns at the bridge`** — accumulator + `stream_and_persist`; round-trip test (frames → accumulator → `conversation_to_ui` == streamed parts), including `tool-output-error` and stream `error`.
4. **`feat(api): persist user message + finalize/abort handling in /api/chat`** — wire `ensure_conversation`/`append_user_message`; aborted-turn flush; disconnect test.
5. **`feat(api): conversation_to_ui hydration + repoint GET /api/sessions`** — switch hydration to the faithful path; keep `messages_to_ui` as legacy fallback; hydration tests covering all part types (build on `9dac604`'s reasoning test).
6. **`feat(api): conversation list/create/title endpoints`** — `GET/POST/PATCH /api/conversations`; derive title from first user message on finish.
7. **`feat(web): conversation sidebar + repointed hydration`** — frontend list + "New chat" via API.
8. **`chore(scripts): optional backfill from harness sessions.db`** — idempotent legacy import.
9. **(doc note, not code) record the alembic trigger** — first non-additive change adopts alembic.

---

## Critical files for implementation

- `backend/penny/api/bridge.py`
- `backend/penny/api/persistence/` (new: `models.py` on its own `Base`, `store.py`, `engine.py`)
- `backend/penny/api/main.py`
- `backend/penny/api/hydration.py`
- `backend/penny/bootstrap.py` (separate `create_all` for the website store)
- `backend/penny/tools/analytics.py` (`run_sql` schema scoping)
