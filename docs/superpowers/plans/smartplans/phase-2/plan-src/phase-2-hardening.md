---
id: phase-2-hardening
label: Hardening & testing
parent: phase-2
sections: [run-sql, email, cron, review-and-amendments, testing]
crosslinks: [phase-2-backend, phase-2-conversations]
---

# Hardening & testing

The fixes from the security review, plus the test surface that proves them.

## Requirements

- A report can only ever reach the signed-in spouse or the household, never a recipient the agent picks.
- Even if the agent is tricked, it cannot delete or alter data through free-form actions.
- Automated background reports always run as a known person and reach only the intended recipients.

## run-sql — run_sql read-only

The agent's free-form SQL path runs on a **dedicated read-only Postgres role** (or DML is rejected before execution). RLS already blocks cross-household reads; read-only `run_sql` closes the within-household prompt-injection *write/destruction* path. Curated `@tool` write functions (recategorize, verify, persister, conversation persistence) keep a normal RLS-scoped read-write connection — writes flow only through typed, reviewed code.

## email — Email tool has no recipient parameter

`send_email_report` takes **no recipient parameter**. Recipients derive entirely from the authenticated context: an individual context emails that user; a joint/household context emails all household members (verified `users.email`). The agent cannot name, add, or influence a recipient — the injection surface is removed, not merely validated.

## cron — Cron principal

Cron builds an explicit `RequestContext` per job and **fails loudly** if its principal env is unset (never runs RLS-unscoped). Two job kinds: per-user individual reports (emailed only to that user) and a household shared report in joint/shared-only mode (emailed to both). Cron uses the same `session_for(ctx)` path as chat.

## review-and-amendments — Review outcome & phase-1a amendments

Reviewed by the `rook` agent. All Critical/High findings are folded in as hard requirements (dev-stub fail-closed and unreachable in prod; auth on every route; no-recipient email tool; JWKS-from-config + `iss`/`email_verified` checks; `owner_user_id` from JWT; CORS required; in-memory tokens; explicit cron context; read-only `run_sql`) with no architectural rework. Two findings belong to **phase 1a** and are recorded there: mandatory `WITH CHECK` on every RLS policy, and a `CHECK (owner_user_id <> nil-uuid)` so the joint sentinel can never collide with a real row.

## testing — Test surface

Postgres-marked where RLS is involved: 401 on missing/invalid/expired/`alg=none`/wrong-`iss`/wrong-`aud`; 403 on unknown user and `email_verified=false`; clerk-mode ignores spoofed `X-Penny-*` headers; startup fails on misconfig/missing CORS origin; atomic idempotent account linking; IDOR blocked across users and households; individual thread hidden from spouse, joint visible to household; DML via `run_sql` rejected while typed writes succeed; the email tool exposes no recipient parameter; disallowed CORS origins blocked.
