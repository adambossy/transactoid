---
id: phase-6-matrix
label: Coverage matrix
parent: phase-6
sections: [dimensions, must-cover, signoff]
crosslinks: [phase-6-guard, phase-6-deliverables]
---

# Coverage matrix

A living, signed matrix is the spine of the audit: it names every dimension of the system that must be examined, who owned that pass, the adversarial evidence, the findings, and a sign-off. Because it is signed dimension by dimension, "we never looked at X" cannot hide. The fan-out workflow spawns one adversarial reviewer per row.

## Requirements

- The owner can see, at a glance, every part of the system that was examined and confirm none was skipped.
- Every dimension carries a recorded adversarial pass and a sign-off before the audit is considered complete.
- Concerns carried forward from earlier phases each land as an explicit must-cover item on the relevant dimension rather than being lost.

## dimensions — The dimensions audited

Each dimension gets an owner, an adversarial pass, and a sign-off. The full set: cross-tenant isolation (every data-access method plus a free-form SQL battery from one household returns zero of another household's rows, and an RLS policy audit); within-household privacy (a spouse's private accounts, conversations, and workspace stay invisible, with joint meaning shared-only); auth (token verification, fail-closed dev stub, direct-object-reference checks on every route, session-mode tamper); web-schema conversations (app-layer scoping correctness with an RLS backstop); secrets (bank-token encryption at rest, never in logs, a key-rotation procedure, secret storage); prompt and agent injection (coaxing the SQL path, the tools, and the reminder flush into cross-tenant reads or exfiltration, plus email-recipient tamper); the R2 access path (opaque tokens, non-listing credentials, keys derived only from isolation lookups, no direct agent access, temp-dir hygiene); open-signup abuse (rate limits on signup and bank linking, cost controls, provisioning idempotency under a race); cutover integrity (legacy data migrates to the correct owner and visibility, no row left mis-tenanted, pending-user handoff cannot be hijacked); transport and infra (TLS, CORS lockdown, hosting config, the read-only agent role's privileges); and dependencies and supply chain (vulnerability scans, pinned versions, the three-repo trust boundary).

## must-cover — Carried-in must-cover items

Concerns surfaced in earlier phases slot in as explicit must-cover rows rather than being re-derived. Phase 1a contributes the mandatory WITH CHECK clause on every isolation policy and the nil-owner sentinel guard. Phase 2 contributes the dev-bypass fail-closed check and the session-listing direct-object-reference case, plus web-schema conversation isolation and the email tool with no recipient parameter. Phase 5 contributes the reminder-injection path — a reminder must reach the model's turn but never the stored transcript. Phase 4 contributes the open-signup abuse surface, and phase 3 contributes cutover integrity. Each is seeded verbatim onto its dimension so the reviewer for that row must exercise it.

## signoff — Sign-off discipline

A dimension is signed off only once its adversarial pass is recorded and its findings are filed; no dimension is left unsigned. A fix in one dimension re-sweeps adjacent dimensions — an auth fix, for example, re-runs the direct-object-reference battery — and a dimension is dry only after K consecutive clean passes. The verified survivors feed the [CI regression guard](guard.html) and the final [gate](deliverables.html).
