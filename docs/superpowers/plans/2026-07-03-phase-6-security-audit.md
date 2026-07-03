# Phase 6 — Security Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> Part of the [Multi-Account Epic](2026-06-27-multi-account-epic-overview.md).
> Spec: [Phase 6 design](../specs/2026-07-03-phase-6-security-audit-design.md).
> **Prev:** [Phase 5 plan](2026-07-03-phase-5-onboarding.md)

**Goal:** Run an agent-driven, coverage-matrix security audit; block go-live on
Critical/High; ship a standing CI regression guard so isolation can't silently
break later.

**Architecture:** Part durable tooling (policy-lint, CI job, dependency scan,
adversarial Playwright E2E — real code deliverables), part repeatable audit
process (a fan-out adversarial workflow + `rook` + `/security-review` over a
signed coverage matrix, each finding verified by a failing test). Every verified
finding ships a regression test that joins the CI guard.

**Tech Stack:** Python 3.12 + pytest (the accumulated Postgres-marked suites),
Playwright (phase-1a harness), the `Workflow` orchestration tool + `rook` agent +
`/security-review` skill, CI (GitHub Actions or the repo's runner), `uv`/`npm
audit`.

## Global Constraints

- **Verification gate (before completing each code task):** from `backend/`:
  `uv run ruff check .` · `uv run ruff format --check .` · `uv run pytest -q`.
- **Finding discipline:** no finding counts until a **failing test or concrete
  repro** demonstrates it; fixes ship with that test flipped green.
- **Gate:** Critical/High block go-live (fixed or written risk-acceptance);
  Medium/Low tracked. Real data beyond the owner's own household must not flow
  until the gate is clear.
- **Postgres suites** need `POSTGRES_TEST_URL` (Neon `penny-test`); the read-only
  `run_sql` suite also needs `POSTGRES_TEST_RO_URL`.
- **Executes last** — after phases 1a–5 are built. Re-runnable after major changes.

## Artifacts (created/maintained by this phase)

- `docs/security/coverage-matrix.md` — the living, signed matrix.
- `docs/security/findings.md` — verified findings + status.
- `docs/security/remediation-ledger.md` — Medium/Low + risk-acceptance records.
- `docs/security/go-no-go.md` — the final memo.
- `backend/scripts/rls_policy_lint.py` + `.github/workflows/security.yml` (or
  equivalent) — the durable guards.
- `frontend/e2e/adversarial.spec.ts` — browser IDOR/cross-tenant checks.

---

### Task 1: Coverage matrix + audit scaffolding

**Files:**
- Create: `docs/security/coverage-matrix.md`, `docs/security/findings.md`,
  `docs/security/remediation-ledger.md`

- [ ] **Step 1:** Create `coverage-matrix.md` with one row per dimension from the
  spec (cross-tenant isolation, within-household privacy, auth, web-schema
  conversations, secrets, prompt/agent injection, R2 access path, open-signup
  abuse, cutover integrity, transport/infra, dependencies) and columns:
  *Dimension · Owner · Adversarial pass (link/date) · Findings · Sign-off*.
  Seed each row's "must-cover" carried-in items verbatim from the spec table.
- [ ] **Step 2:** Create `findings.md` (table: ID · dimension · severity · repro
  test · status ∈ open/fixed/risk-accepted/tracked) and `remediation-ledger.md`
  (Medium/Low + a "Risk acceptances" section: finding · accepted-by · date · why).
- [ ] **Step 3: Commit**

```bash
git add docs/security
git commit -m "docs(security): coverage matrix + findings/remediation scaffolding"
```

---

### Task 2: RLS policy-lint (durable guard)

**Files:**
- Create: `backend/scripts/rls_policy_lint.py`
- Test: `backend/tests/security/test_rls_policy_lint.py` (Postgres-marked)

**Interfaces:**
- Produces: `lint_rls_policies(engine) -> list[str]` — returns a list of
  violations: every table that has RLS enabled but lacks a `USING` **or** a
  `WITH CHECK` clause on its `tenant_isolation` policy, plus every per-household
  table (from a known list) that has **no** RLS enabled or lacks `FORCE ROW
  LEVEL SECURITY`. Empty list = pass. A `__main__` exits non-zero on violations
  (for CI). Reads `pg_policies` / `pg_class.relforcerowsecurity`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/security/test_rls_policy_lint.py
import pytest

pytestmark = pytest.mark.postgres

from backend.scripts.rls_policy_lint import lint_rls_policies  # adjust import to repo layout


def test_clean_schema_has_no_violations(pg_db):
    # pg_db built the full schema incl. migration 011/015 policies (USING+WITH CHECK)
    assert lint_rls_policies(pg_db._engine) == []


def test_detects_missing_with_check(pg_db):
    with pg_db.session() as s:
        import sqlalchemy as sa
        # drop WITH CHECK on one policy to simulate a regression
        s.execute(sa.text("ALTER TABLE derived_transactions DISABLE ROW LEVEL SECURITY"))
    violations = lint_rls_policies(pg_db._engine)
    assert any("derived_transactions" in v for v in violations)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && POSTGRES_TEST_URL=<url> uv run pytest tests/security/test_rls_policy_lint.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`rls_policy_lint.py` queries `pg_policies` (columns `qual` = USING, `with_check`)
and `pg_class.relrowsecurity`/`relforcerowsecurity`, checks each per-household
table (import the canonical table list from the migrations, or hard-code it with
a comment pointing at migration 011/015), and returns human-readable violation
strings. `if __name__ == "__main__":` builds an engine from `DATABASE_URL`,
prints violations, `sys.exit(1)` if any.

- [ ] **Step 4: Run to verify it passes**

Run: same command → PASS; skips without `POSTGRES_TEST_URL`.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/rls_policy_lint.py backend/tests/security/test_rls_policy_lint.py
git commit -m "feat(security): RLS policy-lint (every table has USING + WITH CHECK)"
```

---

### Task 3: Adversarial Playwright E2E (browser IDOR / cross-tenant)

**Files:**
- Create: `frontend/e2e/adversarial.spec.ts`
- Test: the spec itself (Playwright), reusing the phase-1a harness +
  `signInAsTestUser`.

- [ ] **Step 1: Write the failing spec**

`frontend/e2e/adversarial.spec.ts` with cases (prose; implement against the real
selectors/routes):
- **cross-user IDOR:** sign in as B (`browser.newContext`), navigate to A's
  individual conversation URL → expect 404 / no data rendered.
- **cross-household:** B cannot reach A's transactions/reports/workspace via any
  screen or deep link.
- **signed-out:** a protected route renders the sign-in gate, no financial data
  flashes before auth.

- [ ] **Step 2: Run to verify it fails/gaps**

Run: `cd frontend && npx playwright test e2e/adversarial.spec.ts`
Expected: FAIL until the app enforces these (it should, from phases 2/4 — this
codifies it as a regression check; any real failure here is a finding).

- [ ] **Step 3: Make green (or file findings)**

If a case fails for a real reason, file it in `findings.md` (severity), fix,
and re-run. Otherwise wire selectors so the spec passes against the built app.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/adversarial.spec.ts
git commit -m "test(security): adversarial browser E2E (cross-user/cross-household IDOR)"
```

---

### Task 4: CI regression guard

**Files:**
- Create/Modify: `.github/workflows/security.yml` (or the repo's CI equivalent)

**Interfaces:**
- Produces: a required CI job that runs, on every PR: the Postgres-marked suites
  (`uv run pytest -q -m postgres` with `POSTGRES_TEST_URL`/`POSTGRES_TEST_RO_URL`
  from CI secrets → Neon test branch), the full `uv run pytest -q`, the RLS
  policy-lint (`python backend/scripts/rls_policy_lint.py`), the Playwright E2E
  (`cd frontend && npx playwright test` headless), and a dependency scan
  (`uv pip audit` or `uv lock --check` + `npm audit --audit-level=high`).

- [ ] **Step 1:** Author the workflow with those steps; mark it required for merge.
- [ ] **Step 2:** Trigger it (push a no-op branch) and confirm it runs green on
  the current tree; confirm a deliberately-broken RLS policy makes it red
  (sanity — revert after).
- [ ] **Step 3: Commit**

```bash
git add .github/workflows/security.yml
git commit -m "ci(security): required regression job (RLS suites, policy-lint, e2e, dep scan)"
```

---

### Task 5 (process): Run the adversarial audit over the coverage matrix

Not code — the audit pass. Executed with the orchestration tooling; each finding
recorded and verified.

- [ ] **Step 1: Breadth sweep.** Run a fan-out `Workflow` that spawns one
  adversarial reviewer per coverage-matrix dimension (prompt each to *find and
  refute* — cross-tenant leakage, auth/IDOR, injection over `run_sql`/tools/the
  reminder flush, R2 path, secrets, abuse, cutover integrity, transport, deps).
  Each returns candidate findings.
- [ ] **Step 2: Depth passes.** Run `rook` and `/security-review` on the
  highest-risk dimensions (cross-tenant isolation, auth, prompt injection).
- [ ] **Step 3: Verify each candidate.** For every candidate finding, write a
  failing test / concrete repro. Discard the ones that don't reproduce. Record
  survivors in `findings.md` with a severity.
- [ ] **Step 4: Sign off** each matrix dimension once its adversarial pass is
  recorded and its findings are filed. Do not leave a dimension unsigned.

(No commit gate here beyond updating the docs as findings land.)

---

### Task 6 (process): Remediate to the gate

- [ ] **Step 1:** For each **Critical/High**: fix it, flip its demonstrating test
  green (the test joins the CI guard), and re-run that dimension's adversarial
  pass until dry (K consecutive clean). Re-sweep adjacent dimensions after a fix.
- [ ] **Step 2:** For any Critical/High you choose **not** to fix before go-live,
  record a dated risk-acceptance in `remediation-ledger.md` (accepted-by, why).
- [ ] **Step 3:** File **Medium/Low** in the ledger with owner + target (non-blocking).
- [ ] **Step 4: Commit** the fixes + their regression tests as they land
  (conventional messages), and the updated `findings.md`/ledger.

---

### Task 7: Deliverables — report, signed matrix, go/no-go memo

**Files:**
- Finalize: `docs/security/coverage-matrix.md`, `findings.md`,
  `remediation-ledger.md`; Create: `docs/security/go-no-go.md`

- [ ] **Step 1:** Ensure every matrix dimension is signed off and every finding
  has a terminal status (fixed / risk-accepted / tracked).
- [ ] **Step 2:** Write `go-no-go.md`: a one-page statement that all Critical/High
  are resolved-or-accepted (list them), the CI guard is green, and therefore
  real data may flow — or an explicit NO-GO listing the blockers.
- [ ] **Step 3: Commit**

```bash
git add docs/security
git commit -m "docs(security): signed coverage matrix, findings, go/no-go memo"
```

---

## Modularization

**Principle:** the reusable artifacts here are **tooling + process**, not
product code. Carve each so it lifts into a standalone package/playbook with no
Penny-specific coupling in its core — the one product-specific input (Penny's
table list) stays behind config or a discovered list, never hard-coded into the
reusable unit. Avoid premature abstraction: these are thin, single-purpose
guards, not a framework.

- **RLS policy-lint (durable tooling).** `lint_rls_policies(engine) -> list[str]`
  (Task 2) asserts every tenant table has RLS with both a `USING` and a
  `WITH CHECK` clause (+ `FORCE ROW LEVEL SECURITY`) by reading `pg_policies` /
  `pg_class` — pure Postgres introspection.
  - **Seam:** `(engine, table_list) -> violations`; a `__main__` that exits
    non-zero for CI.
  - **Keep OUT of the core:** Penny's concrete table list — pass it in via
    config or discover it from `pg_class` (tables with `relrowsecurity`), so the
    linter carries no knowledge of Penny's schema.
  - *Portable to any RLS-based multi-tenant Postgres app that wants to assert
    every table is fully policy-covered.*

- **CI regression-guard pattern.** The required CI job (Task 4) that runs the
  Postgres-marked suites + policy-lint + adversarial E2E + dependency scan on
  every PR is a reusable shape, independent of the specific tests.
  - **Seam:** a workflow that composes "isolation suites + policy-lint + browser
    IDOR E2E + dep scan" as required-for-merge gates.
  - **Keep OUT of the core:** repo-specific secrets, DB URLs, and suite paths —
    parameterize via CI secrets/vars.
  - *Portable to any app that wants tenant-isolation invariants enforced as a
    standing, can't-silently-break merge gate.*

- **Agent-driven coverage-matrix audit harness (repeatable process).** The
  fan-out adversarial workflow (Task 5) — one reviewer per matrix dimension,
  `rook` + `/security-review` depth passes, each candidate verified by a failing
  test — is a re-runnable audit *process*, not a one-off.
  - **Seam:** a signed coverage matrix (dimensions × owner × pass × findings ×
    sign-off) driving a `Workflow` fan-out with per-dimension adversarial
    prompts; every survivor ships a regression test that joins the CI guard.
  - **Keep OUT of the core:** Penny's specific dimensions and table/route
    inventory — the matrix rows are data, and the prompts reference "each
    dimension" generically.
  - *Portable to any project that needs a repeatable, evidence-gated security
    audit whose findings harden into standing regression tests.*

## Self-Review

**Spec coverage:** methodology (fan-out + rook + verify) → Task 5; coverage
matrix → Tasks 1, 5; triage/gate/remediation → Task 6; CI regression guard →
Tasks 2, 3, 4; deliverables → Tasks 1, 7; UI/UX (no new screens; remediation uses
template) → covered by the gate + Task 3's error-state checks; Browser E2E
adversarial → Task 3. Cutover-integrity dimension → matrix row (Task 1) +
audited in Task 5.

**Placeholder scan:** Tasks 5–6 are intentionally process (audit passes),
described with concrete steps and artifacts rather than code; Tasks 2–4, 7 carry
concrete code/CI/doc deliverables. No TBD/TODO.

**Type consistency:** `lint_rls_policies(engine) -> list[str]`, the artifact
paths under `docs/security/`, and the CI step commands are consistent across
tasks; reuses phase-1a `pg_db`/harness and phase-2 `signInAsTestUser`.

## Execution Handoff

Execute last, after phases 1a–5. Tasks 2–4 (durable guards) are subagent-driven
TDD; Tasks 5–6 are the human-in-the-loop audit-and-remediate loop driven by the
orchestration tooling; Task 7 assembles the go/no-go. Postgres tasks need
`POSTGRES_TEST_URL` (+ `POSTGRES_TEST_RO_URL`) on the Neon `penny-test` branch.
