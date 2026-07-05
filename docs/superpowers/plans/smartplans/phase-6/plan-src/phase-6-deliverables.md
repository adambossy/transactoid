---
id: phase-6-deliverables
label: Gate & deliverables
parent: phase-6
sections: [gate, findings, memo]
crosslinks: [phase-6-matrix, phase-6-guard]
---

# Gate & deliverables

The audit ends in a decision the owner can act on: a blocking gate that keeps real data behind resolved risk, a set of plain documents recording what was found and its status, and a one-page memo declaring go or no-go. Nothing here is a screen — these are readable artifacts.

## Requirements

- The owner can read a findings report, a signed coverage matrix, and a go/no-go memo as plain documents and understand exactly what was checked and what is left.
- No Critical or High finding is silently waived — each is either fixed or carries a dated, signed written risk-acceptance.
- Real data flows beyond the owner's own household only after the gate clears and the CI guard is green.

## gate — The blocking gate

Every verified finding is scored Critical, High, Medium, or Low. Real data cannot flow beyond the owner's own household while any Critical or High is open. Each such finding is either fixed — with its demonstrating test flipped green and joined to the [CI guard](guard.html), then that dimension's adversarial pass re-run until dry — or explicitly risk-accepted in a dated written entry naming who accepted it and why. Medium and Low are recorded in a remediation ledger with an owner and target, non-blocking. The remediation loop re-sweeps adjacent dimensions after any fix.

## findings — Findings & ledger

The findings report lists every verified finding with its severity, its repro or test, and a terminal status of fixed, risk-accepted, or tracked. The signed [coverage matrix](matrix.html) records each dimension as covered, by whom, with its adversarial-pass evidence. The remediation ledger holds the Medium and Low items with owners and targets, plus the written risk-acceptance record for any waived High or Critical. Together they leave a durable, auditable trail that survives re-runs.

## memo — Go / no-go memo

The audit closes with a one-page memo: a plain statement that every Critical and High is resolved or accepted — listing them — that the CI guard is green, and therefore that real data may flow. If any blocker remains, the memo is an explicit NO-GO that names it. This is the artifact the owner reads to decide whether to trust the product with real money data at scale.
