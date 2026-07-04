# Go / No-Go — Multi-Account Epic (2026-07-04)

## Verdict: **GO** (security) — as of the live-Postgres validation

The Phase 6 adversarial audit initially returned **NO-GO** with 1 Critical + 6
High blockers (see history below). All 7 have been remediated (one reviewable
commit each, merged in `96010cf`) and **empirically validated against a live,
genuinely non-superuser Postgres role** (Docker PG 16; owner `penny_owner` and
agent role `penny_agent_ro`, both `rolsuper=f rolbypassrls=f` — so RLS and role
grants genuinely bite, no superuser false-pass):

- **F01 / F06 (Critical/High) — shell tool secret exfiltration:** the `bash`
  tool is removed from the agent toolset. `test_no_shell_tool` green.
- **F02 / F05 (High) — run_sql GUC-override RLS bypass:** a set-once
  `SECURITY DEFINER penny_set_tenant` wrapper (migration 024) on the read-only
  connection + `EXECUTE ON set_config` revoked from PUBLIC. The CTE
  `set_config('app.current_household','<victim>',true)` attack is **denied** and
  the wrapper rejects a second/injected call. `test_run_sql_guc_override` 3/3.
- **F04 (High) — run_sql reads identity tables:** `SELECT` on `users`/`households`
  is **permission-denied** for the agent role; finance reads still work.
  `test_run_sql_identity_tables` 3/3.
- **F03 (High) — key rotation destroys ciphertext:** versioned-key support in the
  token cipher; prior versions still decrypt. Green.
- **F07 (High) — plaintext token fallback:** fail-closed on a missing
  `PENNY_PLAID_TOKEN_KEY` in clerk mode. Green.

Full RLS/isolation regression battery (`test_rls_isolation`,
`test_multitenant_acceptance`, `test_workspace_rls`, `test_phase5_rls`,
`test_billing_rls`, `test_run_sql_readonly`) — all green, no regression.

## Non-blocking items surfaced (track separately)

- **Provisioning-under-RLS gap (phase 4):** `provision_solo_household` seeds
  per-household `categories`; the `categories` WITH CHECK requires a matching
  `app.current_household` GUC, but open-signup provisioning runs with **no
  ambient tenant context**, so on Postgres those INSERTs would be RLS-denied —
  a brand-new open signup may fail to provision on prod. Does NOT affect the
  Phase 3 cutover handoff (cutover users are *claimed* pending rows, not
  provisioned) or SQLite dev (no RLS). Fix before relying on open signup in
  prod. (Two `test_signup_isolation` tests fail for this reason — not a
  remediation regression.)
- The 12 Medium + 13 Low findings remain tracked in `findings.md`.

## Gate on the Phase 3 prod cutover apply

Security is GO. The **cutover apply additionally requires** the re-rehearsal to
pass **with no workarounds** — the first re-rehearsal found two cutover-tool
bugs (reparent `email_receipts` schema defect; finalize conversations-backfill
transaction bug) and a 25th unmapped account (assigned adambossy/shared). Those
are being fixed + the mapping completed; a clean re-rehearsal must verify green
before prod. The frozen backup branch `cutover-frozen-backup-20260704-1408`
stays untouched until the prod `verify` passes.

---

## History — original audit verdict (NO-GO), for the record

The audit's original blocker list (all now closed, above):
- CRITICAL (transport-infra): bash tool passes full server env to subprocess —
  any open-signup user exfiltrates every secret via 'run bash env'.
- HIGH (transport-infra): Plaid token plaintext fallback not fail-closed in clerk mode.
- HIGH (cross-tenant-isolation): run_sql CTE set_config GUC override bypasses RLS.
- HIGH (prompt-agent-injection): same CTE/set_config override on the injection path.
- HIGH (prompt-agent-injection): run_sql reads users/households (no RLS) — PII leak.
- HIGH (secrets): key rotation structurally destroys all ciphertext.
- HIGH (r2-access-path): bash subprocess inherits R2 + all secrets (same root as the Critical).
