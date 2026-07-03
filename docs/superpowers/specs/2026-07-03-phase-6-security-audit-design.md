# Phase 6 — Security Audit — Design

**Status:** Approved design (pending written-spec review)
**Date:** 2026-07-03
**Branch:** `feat/account-creation`
**Part of:** [Multi-Account Epic](../plans/2026-06-27-multi-account-epic-overview.md)
**Depends on:** Phases 1a, 1b, 2, 3 (cutover), 4, 5 — audits everything built.

## Goal

Intensely audit the whole system so personal financial data cannot leak across
households or between spouses, before/while real data is in use. Output: a
verified findings report, a signed coverage matrix, and a standing CI regression
guard — with **Critical/High findings blocking** the flow of real data beyond
your own household.

## Decisions (locked)

- **Agent-driven + coverage matrix.** Adversarial AI agents (`rook`, the
  `/security-review` skill, a fan-out workflow) drive breadth across a structured
  coverage matrix; each finding is independently verified before it counts.
- **Blocking gate + CI regression.** Critical/High are blocking (fixed or
  written risk-acceptance); Medium/Low tracked. The accumulated leakage/RLS
  suites run in CI on every change as a permanent regression guard.
- No external pentest in v1 (revisit for scale); no manual-only checklist.

## Section 1 — Methodology & harness

A structured, agent-driven audit with verify-then-triage discipline:

- **Breadth:** a fan-out workflow spawns one adversarial reviewer per coverage
  dimension; each produces candidate findings.
- **Depth:** `rook` and `/security-review` drive the highest-risk dimensions
  (cross-tenant isolation, auth, injection) deeply.
- **Verification:** every candidate finding gets an independent skeptic pass —
  it doesn't count until a **failing test or concrete repro** demonstrates it.
  This kills plausible-but-wrong findings.
- **Living artifact:** the coverage matrix is signed off dimension-by-dimension,
  so "we didn't look at X" cannot hide.

## Section 2 — Coverage matrix

Every dimension gets an owner, an adversarial pass, and a sign-off. Items
accumulated from earlier phases slot in as **must-cover** rows.

| Dimension | Focus | Carried-in must-cover |
|---|---|---|
| **Cross-tenant isolation** | Every façade method + a `run_sql` battery from household A returns zero B rows; RLS policy audit (USING **and** WITH CHECK on every table); nil-uuid owner guard | 1a WITH CHECK / nil-uuid |
| **Within-household privacy** | Spouse's private accounts / conversations / workspace invisible; joint = shared-only | — |
| **Auth** | JWT verification (alg/iss/aud/exp, JWKS-from-config), fail-closed dev-stub, IDOR on every route, session-mode tamper | 2 dev-bypass, `/api/sessions` IDOR |
| **Web-schema conversations** | Confirm the `tenant_isolation` RLS policy (USING+WITH CHECK) is enabled on conversations/messages and `SET LOCAL` binds on the web-DB connection; app-layer scoping correctness | 2 web-schema isolation (now a built control) |
| **Secrets** | Plaid token encryption at rest + never in logs; **key rotation procedure**; env/secret storage | 1a/2 tokens; deferred rotation |
| **Prompt/agent injection** | Coerce `run_sql` (read-only role holds), tools, and the **reminder flush path** into cross-tenant reads/exfil; email-recipient tamper | 5 reminder injection, 2/8 email tool |
| **R2 access path** | Opaque tokens, no-`LIST` creds, keys only from RLS lookups, no direct agent R2, temp-dir hygiene | 1b R2 path |
| **Open-signup abuse** | Rate-limit signup + Plaid link-token/exchange; cost controls; provision idempotency under race | 4 abuse surface |
| **Cutover integrity** | Legacy-data migration assigns correct owner/visibility per account; no row left with null/wrong tenant; pending-user handoff can't be hijacked | 3 cutover |
| **Transport/infra** | TLS, CORS lockdown, Fly/Neon config, RLS role privileges (read-only agent role) | — |
| **Dependencies/supply chain** | CVE scan (`uv` / `npm audit`), pinned versions, the three-repo trust boundary (agent-harness, agent-ui, Penny) | — |

## Section 3 — Triage, gate & remediation

- **Severity** Critical / High / Medium / Low, assigned to every *verified*
  finding (a finding isn't counted until a failing test/repro demonstrates it).
- **Blocking gate:** real data beyond your own household cannot flow while any
  **Critical or High** is open. Each is either fixed (with a regression test
  proving the fix) or **explicitly risk-accepted in writing** — a dated entry
  naming who accepted it and why. Never silently waived.
- **Medium/Low** tracked in a remediation ledger with owner + target, non-blocking.
- **Remediation loop:** fix → the finding's demonstrating test flips green →
  re-run that dimension's adversarial pass until it's dry (K consecutive clean
  passes) → sign off the row. A fix in one dimension re-sweeps adjacent
  dimensions (e.g., an auth fix re-runs the IDOR battery).

## Section 4 — CI regression guard

The isolation guarantees become permanent. Promote the accumulated
Postgres-marked suites into a required CI job (Neon test branch as
`POSTGRES_TEST_URL`):

- cross-household leakage, within-household privacy, joint-session, workspace RLS (1a/1b)
- auth 401/403/IDOR battery, conversation scoping (2)
- signup isolation (4), reminder e2e — reminder reaches the LLM turn but never
  the stored transcript (5)
- the **Playwright E2E** suites (auth, signup/invite, onboarding, conversation
  isolation) headless
- a **dependency scan** (`uv` / `npm audit`) and a **policy-lint** asserting
  every RLS table has USING **and** WITH CHECK.

CI red = isolation regressed = merge blocked.

## UI/UX Requirements

- As an auditor, I can run browser-driven adversarial checks against the real
  app — attempting cross-tenant and cross-user access through the UI and URLs —
  and see them blocked, not just assert it at the API layer.
- As a user, I notice **no UI change** from the audit; it introduces no new
  screens. Any remediation that does touch UI (e.g., a rate-limit / "try again
  later" state on signup or bank-linking) uses the shared UI template primitives
  and shows a clear, non-leaky error.
- As the owner, I can read the findings report, coverage matrix, and go/no-go
  memo as plain documents.

All new screens (if any remediation adds one) use the shared UI template
primitives (Header, Footer, Logo, color tokens, type scale, font stack) — no
bespoke styling — responsive, with loading, empty, and error states, and the app
shell consistent across screens.

## Browser E2E validation (Playwright)

Adversarial browser E2E, reusing the phase-1a harness + `signInAsTestUser`:

- **Cross-user IDOR (UI):** signed in as user B, navigating to user A's
  individual conversation URL is blocked (404); B never sees A's data in any
  rendered view.
- **Cross-household (UI):** a user in household B, driving the app, cannot reach
  household A's transactions, reports, or workspace through any screen or link.
- **Signed-out access:** protected routes/screens redirect to sign-in; no
  financial data renders before auth.
- **Abuse surface:** repeated signup / link-token requests hit the rate limit
  and show the shared-template error state (added as remediation if the audit
  flags it).

These run headless in CI alongside the regression suites.

## Deliverables

1. **Findings report** — every verified finding: severity, repro/test, status
   (fixed / risk-accepted / tracked).
2. **Signed coverage matrix** — each dimension marked covered, by whom, with its
   adversarial-pass evidence.
3. **Remediation ledger** — Medium/Low with owners + targets; the written
   risk-acceptance record for any waived High/Critical.
4. **CI wiring** — the regression job + Playwright E2E + dependency scan +
   policy-lint, green.
5. **Go/no-go memo** — a one-page statement that all Critical/High are
   resolved-or-accepted, i.e., real data may flow.

## Testing strategy

The audit *is* testing, but it produces durable tests: every verified finding
ships with a regression test that becomes part of the CI guard (Section 4). The
adversarial passes themselves are re-runnable (the fan-out workflow + `rook`
prompts are saved so the audit can be repeated after major changes).

## Out of scope

- External professional pentest (revisit before public/at-scale launch).
- Formal compliance certification (SOC2, etc.).
- Fixing Medium/Low findings before go-live (tracked, non-blocking).

## Future work

- Schedule a recurring lightweight re-audit (the saved workflow) on a cadence.
- Reconsider an external pentest and secret-rotation automation as the user base
  grows beyond the household.
