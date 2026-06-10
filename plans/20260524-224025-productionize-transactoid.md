# Productionize Transactoid — Beta Plan

**Status:** Draft / pending decisions noted below.
**Target audience:** invited beta of dozens + maintainer's family.
**Compliance posture:** minimum required (no formal SOC 2 at this stage).
**Synthesized from:** architecture proposal, security (rook) review, structural (knox) audit, and web research.

---

## 1. Decisions

| Area | Decision | Rationale |
|---|---|---|
| Auth provider | **Clerk** (primary) or **self-hosted gotrue** (if portability is paramount) | Clerk: $0 to 50K MAU, JWT-portable, fastest beta. Self-hosted gotrue: zero lock-in, you keep the schema even if you move off Supabase. Both terminate in the same FastAPI middleware. See §6 if you want portability over speed. |
| Tenancy enforcement | **Postgres RLS** + `SET LOCAL app.current_user_id` per transaction | RLS is portable across any Postgres host. `SET LOCAL` (not `SET`) is mandatory — otherwise the GUC leaks across pooled connections and cross-tenant data leaks. |
| Sandbox model | **One Fly Machine per user**, lazy-created on first sign-in, suspended on idle, resumed via `fly-replay` | Suspend+resume is hundreds of ms via Firecracker snapshots; idle cost is ~$0.15/GB-mo storage + cents. At dozens of users, infra is rounding error. |
| Routing | **tx-edge** (stateless) verifies JWT → emits `fly-replay: instance=<machine_id>; app=tx-sandbox` → user's Machine **re-verifies JWT** | Defense-in-depth: edge proves routing, Machine proves identity. Machine compares `JWT.sub` to its own `USER_ID` env var and rejects on mismatch. |
| Frontend ↔ backend stream | **SSE via fly-replay**, using the Vercel AI SDK v5 UI Message Stream Protocol | SSE works through `fly-replay`; WebSocket upgrades do not. AI SDK v5 protocol is documented and stable. |
| Python ↔ AI SDK adapter | **Pydantic AI's `VercelAIAdapter`** (or `fastapi-ai-sdk` if not on Pydantic AI), targeting **v5** | Handles SSE encoding, tool-approval, MCP dynamic tools. v6 is opt-in. |
| Plaid environment | Start on **Trial plan** (auto-approved, ~10 Items, real Production data); request full Production review at the 11th user | Removes the security questionnaire from the critical path of beta launch. |
| Secret-at-rest | **App-layer envelope encryption** (`PyNaCl` SecretBox) with a master key in Fly secrets; migrate to cloud KMS when economics justify | Acceptable for sub-5K-customer GLBA posture; can be upgraded to AWS/GCP KMS later without schema change. |
| LLM API keys | **Platform-issued** keys with per-user daily/monthly cents cap in a `usage_ledger` table | BYO is a sign-up cliff; platform-issued is the right beta default. Revisit when one user becomes expensive. |
| Persistent workspace per sandbox | **Fly volume** per Machine for `~/.transactoid` (budget.md, scratch, agent memory) | Markdown file is source of truth; back up via Fly volume snapshots. Don't sync to R2 — dual source of truth drifts. |
| Amazon scraping | **Deferred** | Out of scope for v1 beta. |
| Plaid OAuth redirect | **Centralize** at `tx-edge/plaid/callback`, push completion back to user's Machine via internal `fly-replay` | The current `localhost:8443` server is fundamentally incompatible with remote sandboxes — must be deleted, not adapted. |
| Frontend stack | **Next.js + Vercel AI SDK UI**, deployed on Fly | Keeps everything on one platform; Vercel SDK UI works against any backend that speaks its SSE protocol. |

### Open decisions (need your input before phase 2)

1. **Clerk vs. self-hosted gotrue.** Clerk = 1 day to integrate, medium lock-in (JWT-portable but session import is non-trivial). gotrue = ~3–5 days to stand up, zero lock-in. Which trade do you prefer?
2. **Per-user volume?** Adds $0.15/GB-mo per user. Worth it for budget.md + agent memory? Alternative: keep state in Postgres rows (`user_files` table). I lean volume — your existing skills/memory code assumes a filesystem.
3. **MCP server in the sandbox: FastMCP same as today, or refactor?** Knox's #1 finding is that `mcp/server.py` initializes everything at import time. We need to move that into a factory; cleanest is to also gate on a startup-time JWT-matched `USER_ID` env var.

---

## 2. Target architecture

```
                +-----------------------------+
                |   Next.js (Fly app: tx-web) |   issues JWT (Clerk)
                +--------------+--------------+
                               |  HTTPS / SSE (AI SDK v5 protocol)
                               v
                +-----------------------------+
                |   tx-edge (Fly app)         |   stateless
                |   - JWT verify (JWKS)       |
                |   - /plaid/callback         |
                |   - resolves user→machine   |
                |   - mints fly-replay        |
                +--------------+--------------+
                               |  fly-replay: instance=<mid>; app=tx-sandbox
                               v
            +------------------+-------------------+
            |   tx-sandbox  (Fly app, N machines)  |
            |   ONE Machine per user_id            |
            |   - JWT re-verify (sub == USER_ID)   |
            |   - ChatKit/AI SDK SSE server        |
            |   - in-sandbox agent harness         |
            |   - MCP tools (sync, run_sql, ...)   |
            |   - vol:/app/.transactoid per user   |
            |   - calls Plaid Production           |
            +------------------+-------------------+
                               |  shared async pool;
                               |  SET LOCAL app.current_user_id per tx
                               v
                +-----------------------------+
                |   Postgres (Supabase now)   |
                |   RLS on every user table   |
                +-----------------------------+

         +-------------------------------+
         |  tx-cron (manager, exists)    |   one schedule row per (user_id, prompt_key)
         |  per-user scheduled runs      |   spawns Machines in tx-sandbox with USER_ID env
         +-------------------------------+
```

Four Fly apps total: **tx-web** (Next.js), **tx-edge** (FastAPI stateless), **tx-sandbox** (one Machine per user), **tx-cron** (extends existing `ops/cron-manager/`).

### Auth + tenancy flow (the critical path)

1. User signs in on tx-web → Clerk JWT (audience `transactoid`, `sub = user_id`).
2. Frontend opens SSE to `tx-edge.fly.dev/api/sandbox/*` with `Authorization: Bearer <jwt>`.
3. tx-edge verifies JWT (JWKS, cached) → looks up `user_machines(user_id) → machine_id` → returns `fly-replay: instance=<mid>; app=tx-sandbox`.
4. Fly's edge re-dispatches the SSE stream to that Machine; auto-starts if suspended.
5. Sandbox receives request → **re-verifies JWT** → checks `jwt.sub == os.environ["USER_ID"]` → 403 on mismatch.
6. Agent loop opens a DB transaction → `SET LOCAL app.current_user_id = '<USER_ID>'` → runs queries. RLS policies enforce isolation.

The seam at (5) is what stands between a routing-layer bug and a cross-tenant data leak. **Required, not optional.**

### RLS policy template

```sql
ALTER TABLE plaid_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY pi_owner ON plaid_items
  USING (user_id = current_setting('app.current_user_id')::uuid);
-- Same for: plaid_transactions, derived_transactions, merchants,
-- categories, tags, transaction_category_events, amazon_*.

-- Junction tables via FK:
CREATE POLICY tt_owner ON transaction_tags
  USING (EXISTS (
    SELECT 1 FROM derived_transactions dt
    WHERE dt.transaction_id = transaction_tags.transaction_id
      AND dt.user_id = current_setting('app.current_user_id')::uuid
  ));
```

`Category` becomes **per-user**, seeded from `configs/taxonomy.yaml` on signup. Rationale: categories are mutated by the agent (rules, splits, merges) — that's user state, not platform state. Per-user trades LLM cache reuse for correctness; the right call.

---

## 3. Blocking security gaps in current code

These must be closed before any non-maintainer user signs up. Sorted by severity; cross-referenced from rook + knox findings.

### B-1: `run_sql` MCP tool is unrestricted raw SQL passthrough
- `src/transactoid/ui/mcp/server.py:302-327`, `src/transactoid/adapters/db/facade.py:125-139`
- Today: any caller (or a prompt-injected agent) can `DROP TABLE`, `DELETE FROM`, `UPDATE` everything.
- Fix: (a) restrict to `SELECT`-only via parse check; (b) open transaction `READ ONLY`; (c) JWT-gate the MCP endpoint.
- Effort: 1–2 days.

### B-2: Plaid access tokens stored in plaintext
- `src/transactoid/adapters/db/models.py:306` (`PlaidItem.access_token: Text`)
- Today: anyone with DB read (backup, `run_sql`, future SQLi) gets live bank-API credentials.
- Fix: App-layer envelope encryption with PyNaCl SecretBox. Master key in Fly secrets. Rename column to `access_token_encrypted` storing `nonce || ciphertext`. Decrypt only in `PlaidClient` at use site.
- Effort: 2–3 days.

### B-3: No auth on any server entrypoint
- `src/transactoid/ui/{mcp,acp,chatkit}/server.py` — all open.
- Fix: FastAPI dependency that verifies Clerk JWT (JWKS-cached) before any handler. Sandbox additionally checks `jwt.sub == USER_ID` env.
- Effort: 2–3 days.

### B-4: No RLS / no `user_id` column on any table
- All tables (`plaid_items`, `derived_transactions`, etc.) implicitly assume one user.
- Fix: Alembic migration to add `user_id uuid NOT NULL` everywhere (nullable → backfill maintainer's ID → not null); enable RLS; install policies; switch DB façade to set `SET LOCAL app.current_user_id` per transaction; integration test that runs as user A and asserts zero rows leak from user B.
- Effort: 5–8 days. Highest-touch change in the codebase.

### B-5: `.env` rotation
- `.env` is NOT git-tracked (confirmed by rook), but lives plaintext on dev workstations. Contains a live `PLAID_PRODUCTION_SECRET`, `PLAID_ACCESS_TOKEN`, LLM keys, SMTP password, R2 keys.
- Fix: Rotate ALL credentials before any non-maintainer user accesses the deployment. Move per-app secrets to Fly secrets. Add `.certs/` to `.gitignore` explicitly. Remove `PLAID_ACCESS_TOKEN` from env entirely (it belongs encrypted in the DB row).
- Effort: 2–4 hours.

### B-6: `localhost:8443` Plaid redirect server fundamentally broken for remote sandboxes
- `src/transactoid/adapters/clients/plaid_link.py`
- Today: starts a local HTTPS server, writes to `/tmp/transactoid_plaid_*` files, opens `webbrowser.open()`. None of these work on a remote Fly Machine.
- Fix: Centralize OAuth callback at `tx-edge.fly.dev/plaid/callback`. Link-token creation embeds signed `state = {user_id, nonce}`. Callback verifies state, exchanges public token, encrypts, persists via internal call to sandbox (fly-replay POST). Delete `localhost:8443` server, `.certs/`, `/tmp/` IPC entirely.
- Effort: 3–5 days.

### H-1: Prompt-injection blast radius through transaction memos
- Plaid descriptors/memos feed into LLM prompts; agent has `run_sql` write access.
- Fix: (depends on B-1) SELECT-only + a separate DB role for `run_sql` queries that has `BYPASSRLS = false` and no SELECT on `plaid_items` (token table). Truncate/sanitize merchant descriptors before context.
- Effort: 1 day after B-1.

### H-2: World-readable `/tmp` token files
- `plaid_link.py:32-33,222-237` — `/tmp/transactoid_plaid_*` written with `open("w")`, no `chmod 0o600`.
- Subsumed by B-6 (deleting the redirect server entirely).

### H-3: Data Transparency Messaging not configured for Plaid Production
- `plaid_link.py` `create_link_token_and_url` does not pass `use_cases` — Link will refuse to open in Production.
- Fix: Pass `use_cases=["PERSONAL_FINANCE_MANAGEMENT"]`; configure use case in Plaid Dashboard.
- Effort: 2 hours.

### M-1: `execute_raw_sql` commits writes inside the session
- `adapters/db/facade.py:125-139` — `session()` ctx commits on success.
- Fix: Open `READ ONLY` transaction for `run_sql`. Subsumed by B-1's SELECT-only restriction.

### M-2: `recategorize_merchant` accepts any `merchant_id` without ownership check
- `ui/mcp/server.py:99-131`. Subsumed by RLS once B-4 lands.

---

## 4. Structural refactors required before multi-tenancy

From knox's audit — these aren't security holes today but will break under multi-tenancy.

| Issue | Where | Fix |
|---|---|---|
| Module-level singletons (`db`, `taxonomy`, `persist_tool`, etc.) | `ui/mcp/server.py:36-52` | Move to factory function called by `mcp.run()`; pass via closure. Tests stop opening real DB connections. |
| `_category_id_cache: dict[str, int]` process-global | `taxonomy/loader.py:42-71` | Move to instance var on a user-scoped `TaxonomyService`. |
| `_initialized_roots` global set keyed on path | `bootstrap/initialization.py` | Key on `(user_id, path)`, accept `user_id` parameter. |
| `FileCache` defaults to `Path(".cache").resolve()` | `adapters/cache/file_cache.py:30` | Thread per-user cache dir through `Categorizer` ctor; don't rely on cwd isolation. |
| `~/.transactoid` workspace default | `workspace.py:15-31` | OK in per-Machine isolation; document that the assumption is "Machine = user". |
| `MerchantRulesLoader` caches `self._content` for process lifetime | `rules/loader.py:44-70` | OK for one-user sandboxes; flag that any shared usage requires invalidation. |
| Loguru bindings have no `user_id` context | throughout | Add a request-scoped contextvar that all bind sites pick up; needed for usage tracking + abuse triage. |

---

## 5. Phased rollout

Each phase ends in a working, demoable state. Don't merge until the listed gates pass.

### Phase 0 — Pre-work (1 week)
- B-5: rotate all `.env` secrets, move to Fly secrets.
- Spike: validate **`fly-replay` cross-app SSE preservation** with a 30s stream. This is the load-bearing assumption of the whole topology (architecture agent's P0 risk). Until proven, don't commit further.
- Spike: validate Pydantic AI `VercelAIAdapter` against a minimal Next.js + AI SDK v5 frontend.
- Decide: Clerk vs. self-hosted gotrue (decision §1 #1).

**Gate:** SSE through fly-replay confirmed end-to-end; auth provider chosen.

### Phase 1 — Multi-tenant data model (2 weeks)
- Add `users` table seeded from Clerk webhook (`user.created`).
- Alembic migration: `user_id uuid NOT NULL` on every user-scoped table, backfilled with maintainer's user_id.
- Enable RLS + install policies on every table (template in §2).
- Refactor DB façade: `SET LOCAL app.current_user_id` first statement of every tx.
- Refactor `mcp/server.py` from module-level singletons to factory.
- Per-user taxonomy seed on user creation (copy `configs/taxonomy.yaml`).
- Integration test: cross-tenant read returns zero rows; CI-gated.

**Gate:** all existing tests pass with a maintainer user_id; cross-tenant integration test green.

### Phase 2 — Auth + edge routing (1 week)
- Stand up tx-edge Fly app: stateless FastAPI with JWKS-cached JWT verifier.
- JWT verification dependency in every existing handler.
- `user_machines` registry table; tx-edge resolves user→machine, emits `fly-replay`.
- Sandbox JWT re-verification: `jwt.sub == os.environ["USER_ID"]` or 403.
- B-3 closed.

**Gate:** two test users on two Machines; user A's request rejected when routed to user B's Machine.

### Phase 3 — Token encryption + Plaid redirect (1 week)
- B-2: encrypt `plaid_items.access_token` via PyNaCl SecretBox; rename column.
- B-6: tx-edge owns `/plaid/callback`; signed `state` carries `user_id`; completion pushed to sandbox via internal `fly-replay` POST.
- Delete `plaid_link.py` localhost server, `/tmp/` IPC, `.certs/`.
- H-3: configure DTM use cases.

**Gate:** Plaid Production sandbox connects end-to-end through tx-edge for two distinct users.

### Phase 4 — Per-user sandbox provisioning (1 week)
- On `user.created` Clerk webhook: create Fly Machine + volume via Machines API.
- Default `auto_stop_machines = "suspend"` for sub-second resume.
- Per-user volume mounted at `/app/.transactoid`.
- Seed budget.md + memory/index.md from template on first chat.

**Gate:** new user signup provisions a sandbox; first chat resumes from suspended state in <1s.

### Phase 5 — Frontend (1 week)
- Next.js app with Clerk components + Vercel AI SDK UI.
- Pydantic AI `VercelAIAdapter` in the sandbox emits v5-protocol SSE.
- Onboarding flow: Plaid Link → taxonomy review (read-only initially) → budget chat → first sync.
- Deploy as tx-web on Fly.

**Gate:** maintainer + 1 family member can sign up, connect Plaid, see categorized transactions.

### Phase 6 — Security restrictions (~3 days)
- B-1: `run_sql` SELECT-only + read-only DB role + parse check.
- H-1: input sanitization on merchant descriptors before LLM context.
- Per-user LLM usage ledger + daily cap enforcement.
- Per-user logging context (loguru `bind(user_id=...)` via contextvar).

**Gate:** prompt-injection test (malicious memo trying to exfil via `run_sql`) blocked.

### Phase 7 — Compliance + launch prep (~3 days)
- Privacy policy (Termly/iubenda template + Plaid-specific section).
- Terms of service.
- Incident-response runbook (state breach notification chart from IAPP).
- Submit Plaid Trial-plan onboarding (auto-approved); plan for security questionnaire at user #11.
- `.env.example` committed; `.certs/` in `.gitignore`.

**Gate:** beta invitation goes out.

Total: ~7–8 weeks of focused work.

---

## 6. The Clerk vs. self-hosted gotrue trade

You said "maybe not Supabase since I'll likely move off." Two interpretations:

- **"Off Supabase Postgres"**: Either auth provider works. Clerk and gotrue both terminate in your FastAPI middleware → set GUC → RLS. Portable.
- **"Off Supabase Auth specifically"**: Then Clerk is fine (it was never Supabase Auth). Gotrue is *also* fine if self-hosted — Supabase open-sourced it; it's a Go service that takes any Postgres connection string.

**My recommendation: Clerk for the beta.** Reason: the Next.js DX (drop-in `<SignIn>`, `<UserButton>`, JWT in cookies) saves 3–5 days you'd spend assembling gotrue + OAuth callbacks. If you move providers later, you re-issue sessions — a one-time migration script, not a database rewrite.

**If portability matters more than speed:** self-hosted gotrue on a small Fly Machine. The `auth` schema travels with your Postgres; switching DB hosts is now just `pg_dump`.

Either way, RLS in your application schema is portable. That's the load-bearing decision, and it's the same in both worlds.

---

## 7. Compliance summary

- **GLBA Safeguards Rule**: applies (you're a fintech aggregator handling NPI), but you're **sub-5,000 customers → exempt from the heaviest deliverables** (written risk assessment, CISO designation, board reports, annual pen tests). Still required: encryption in transit/at rest, access controls, basic monitoring, privacy notice, incident response plan.
- **State privacy laws (CCPA/VCDPA/CPA/CTDPA)**: thresholds are 25K–100K consumers; **you're well below**. Be CCPA-compliant in spirit (right to delete, no sale of data) in your privacy notice.
- **Breach notification**: applies at any size. Have a runbook with state-by-state timelines (30/45/60 days) ready before launch.
- **Plaid**: **Trial plan** is auto-approved up to 10 Items — start there. Submit Plaid's security questionnaire (~60–80 questions) when you anticipate the 11th user. SOC 2 not required at this scale. Token encryption at rest, app-layer envelope encryption is acceptable.
- **Privacy notice + ToS**: required before non-maintainer users sign up. Termly/iubenda fintech templates + Plaid-specific data-handling section.

---

## 8. Self-critique (carried from architecture agent)

1. **`fly-replay` + cross-app SSE is the load-bearing assumption.** Fly's docs document the primitives separately but not the streaming + cross-app combination. **Spike this before committing.** Fallback: tx-edge holds the connection itself as a reverse proxy — costs latency and a hop but unblocks shipping.
2. **`SET LOCAL` requires every code path to be transactional.** `db.execute_raw_sql` and bulk-write methods need an audit. CI integration test (user A reads → user B's rows = 0) is the gate.
3. **Per-user Machine breaks "agent watching at 3am" use cases.** If a Plaid webhook fires while the Machine is suspended, it auto-starts via fly-replay, but you eat the resume latency. Document that this product isn't real-time-critical.
4. **Clerk pricing at scale.** Free to 50K MAU but custom JWT claims (needed for `user_id`) may be on a paid tier. Verify before committing; WorkOS AuthKit swaps in cleanly if needed.
5. **One-machine-per-user vs. one-per-session.** If a user needs two concurrent agent runs (cron + chat simultaneously), the current design serializes them. Probably fine for beta; flag if it bites.

---

## 9. What I need from you to proceed

1. Clerk vs. self-hosted gotrue?
2. Per-user volume yes/no?
3. Confirm: platform-issued LLM keys with usage caps (vs. BYO)?
4. Confirm Phase 0 spike order: SSE-through-fly-replay first, then auth-provider, then implementation?
