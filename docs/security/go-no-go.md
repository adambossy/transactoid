# Go / No-Go — Multi-Account Epic (2026-07-04)

## Verdict: **NO-GO**

All 12 dimensions were adversarially reviewed and signed (coverage present, findings filed). The verdict is NO-GO: one CRITICAL and six HIGH confirmed findings are unresolved. The dominant theme is the agent's own tool surface breaching tenant and secret boundaries: the bash tool leaks the entire server environment to any open-signup user (CRITICAL, surfaced in both transport-infra and r2-access-path), and run_sql — unvalidated, passing raw SQL — enables both a CTE/set_config GUC override that defeats RLS on financial tables and a direct read of the unprotected users/households identity tables (three HIGHs across cross-tenant-isolation and prompt-agent-injection). Two secrets/transport HIGHs round out the blockers: Plaid tokens fall back to plaintext-at-rest in clerk mode without failing closed, and key rotation is structurally impossible without orphaning all ciphertexts. Production Postgres RLS, Clerk auth, encryption-at-rest, and web/finance schema segregation are largely well-designed and hold as the primary fences; the remaining mediums/lows are mostly SQLite-dev-only gaps, defense-in-depth omissions, transient-cutover-script issues, and supply-chain pinning. Recommended gate-blockers before go-live: remove or env-strip/flag-gate the bash tool; restrict the run_sql read-only role (REVOKE set_config EXECUTE, revoke SELECT on users/households, enforce search_path); fail closed on PENNY_PLAID_TOKEN_KEY in clerk mode; and add versioned-key support before any rotation. Live Postgres RLS enforcement (POSTGRES_TEST_URL) and the CTE execution-order confirmation were not run in-session and should be validated on the Neon test branch.

## Blockers (Critical/High — must be fixed or risk-accepted before real data flows)

- CRITICAL (transport-infra): bash tool in production toolset passes full server environment to subprocess — any open-signup user can exfiltrate every secret (DATABASE_URL, PENNY_PLAID_TOKEN_KEY, R2/Plaid/Clerk keys) via 'run bash env'
- HIGH (transport-infra): Plaid access token plaintext fallback not fail-closed in clerk mode — missing PENNY_PLAID_TOKEN_KEY silently stores bank tokens as plaintext at rest
- HIGH (cross-tenant-isolation): run_sql GUC override via CTE set_config bypasses the RLS tenant fence — reads any household's financial data
- HIGH (prompt-agent-injection): Single-statement CTE/set_config GUC override may bypass RLS on financial tables (same class as the cross-tenant-isolation finding, on the agent-injection path)
- HIGH (prompt-agent-injection): run_sql can read users and households tables (no RLS policy) — cross-tenant PII leak of all emails and Clerk IDs
- HIGH (secrets): Key rotation is structurally unimplemented — bumping _ACTIVE_VERSION permanently destroys all existing ciphertexts, failing precisely during a compromise-driven rotation
- HIGH (r2-access-path): bash tool subprocess inherits full process env including R2 and all other secrets (same root cause as the transport-infra CRITICAL, filed as the R2 exfiltration path)

Real financial data must not flow through the multi-tenant path (i.e. the Phase 3 prod cutover apply) until these blockers are resolved and this memo flips to GO.
