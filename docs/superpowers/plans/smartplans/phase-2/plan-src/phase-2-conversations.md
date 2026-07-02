---
id: phase-2-conversations
label: Conversation scoping
parent: phase-2
sections: [schema, scoping, idor]
crosslinks: [phase-2-backend]
---

# Conversation scoping

The `conversations` table lives in the web schema — a **separate engine/DB**, so phase 1a's Postgres RLS does not automatically cover it. Phase 2 makes conversations tenant-scoped and records the mode chosen at creation.

## schema — Schema additions

`conversations` gains `household_id`, `owner_user_id`, and `session_mode` (individual | joint), set at creation and **immutable**. **Visibility derives from `session_mode`** rather than a separate column: an individual conversation is private to its owner; a joint conversation is visible to the whole household. One source of truth — the mode you picked also decides who can see the thread.

## scoping — Store filtering

Every read/write filters by `household_id == ctx.household AND (owner_user_id == ctx.user OR session_mode == 'joint')`, and stamps `owner_user_id`/`household_id` from the `RequestContext` on creation — never from the client. On `/api/chat` the backend reads the conversation's stored `session_mode` to build the turn's context ([backend](backend.html)); a joint conversation sets the nil-user sentinel so RLS returns shared-only. Enforcement is app-layer here, with the same RLS policy as a backstop if the web DB is Postgres.

## idor — Closing the IDOR

**Every route is authenticated**, including `GET /api/sessions/{id}`, which does an ownership check *before* querying — closing the direct-object-reference leak where a guessed conversation UUID exposed full chat history. A default-deny routing convention: every new route must make a deliberate auth decision. Web-schema isolation is an explicit phase-6 audit item regardless.
