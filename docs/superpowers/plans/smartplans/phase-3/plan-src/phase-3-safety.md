---
id: phase-3-safety
label: Safety & validation
parent: phase-3
sections: [backup, rehearse, validate]
crosslinks: [phase-3-assign]
---

# Safety & validation

The cutover touches real financial data once, so the safety machinery matters as much as the migration itself.

## backup — Frozen-branch backup

Step zero takes a frozen Neon branch of production — the restore point — and leaves it untouched until the final verify stage passes. It is separate from the rehearsal branch clone. If the production apply goes wrong, production is restored from that frozen branch. A pre-apply snapshot is also taken immediately before the production run.

## rehearse — Rehearse before production

The entire sequence runs first on a separate Neon branch clone: every stage, end to end, with its verify. Every stage is idempotent and resumable and supports a dry run that prints the planned changes without writing. Only after the rehearsal's verify passes — and the pre-apply snapshot is taken — does the cutover run against production.

## validate — Validation

The proof is end to end through the real UI, reusing the phase-1a Playwright harness. After cutover and signup, signing in as you shows your assigned accounts plus shared ones; signing in as your wife shows hers plus shared ones, and an assertion confirms your private accounts never render in her session. The Phase-6 isolation suites also run against the migrated dataset. The cutover adds no new screens; any incidental UI would use the shared UI template primitives.
