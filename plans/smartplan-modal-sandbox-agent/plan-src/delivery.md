---
id: delivery
label: Delivery plan
parent: root
sections: [phases, gates, risks]
crosslinks: [packaging, image-bake, assumptions, security]
---

# Delivery plan

Six phases, dependency-ordered, each independently verifiable and each leaving the system working. Chat on main keeps functioning until the final cutover flag flips.

## Requirements

- At the end of every phase, the existing chat experience still works and the new piece is demonstrated by a runnable check, not an assertion.
- The cutover to sandboxed turns is a reversible switch, not a rewrite of the chat path.

## phases — Phases

- **Protocol and runner, locally.** Create `sandbox/` (protocol plus runner). Event codec with round-trip tests over every event type; runner server runnable as a local process; the runner's turn-result callback fired on `RunEnd` against a stub. A golden test drives a scripted fake agent through `POST /turns` to SSE and asserts byte-identical replay from `from_seq=0`. No Modal, no Penny changes.
- **MCP tool server on Fly.** The adapter exposing existing toolsets over streamable-HTTP MCP with capability-token tenancy. Gate: a harness `MCPServerHTTP` client (in a test) lists and calls `run_sql`/sync with results identical to in-process calls, against the Neon test branch; a cross-tenant token test returns denial.
- **Secrets proxy Function.** Deploy the proxy app; registration/revocation admin API; Gemini streaming through it via the injected-client workaround (plus the upstream harness `base_url` fix filed). Gate: a runner-shaped client completes a streamed model call with only a capability token; a revoked token gets 401 mid-conversation; usage lands on the ledger hook.
- **Modal lifecycle and image bake.** `deploy/sandbox` image build; `backend/penny/sandboxes/` lifecycle module (create/restore, the reaper state machine with the reap-lease/epoch, conversation-sandbox records). Gate: scripted end-to-end — cold create at or under budget, turn, reaper snapshots-then-terminates, restore with workspace intact, new tunnel URL re-resolved; plus the two races: a turn arriving mid-snapshot steals the box back (no terminate, no lost turn), and a turn arriving post-commit cold-restores. Denylist and import-time CI checks green.
- **Wire the chat path plus resume plus durability.** `/api/chat` dispatches turns to the runner behind a `PENNY_SANDBOX_TURNS` flag; frame buffer plus `GET /api/chat/{id}/stream`; Fly-side re-attach sweep; the `POST /runs/{id}/cancel` path wired to the UI stop button; the turn-result persist endpoint on Fly; the idle-reaper as a Fly cron sweep over real conversations. Gate: browser refresh mid-turn replays and continues; killing Fly's SSE pull mid-turn recovers via `from_seq=0` with no duplicate persistence; a user stop mid-turn aborts the run and stops model spend; a sandbox killed mid-idle loses no completed turn (results already persisted); flag off equals today's behavior exactly.
- **Hardening and cutover.** Inbound/outbound allowlists on, segregation guardrail tests, latency measurements (first-token cold/warm/restore) recorded against budgets, `REQUIREMENTS.txt` plus agent docs updated, flag default flipped. Gate: the security checklist walked item-by-item against the live system, **plus all four End-to-end verification scenarios green** in CI against `penny-test` plus dev Modal.

## gates — Cross-phase verification discipline

- Standard repo gate every phase: `ruff check`, `ruff format --check`, `pytest -q` — extended to the `sandbox/` project.
- Phases 2 and 3 run against the `penny-test` Neon branch and a dev Modal environment; nothing in this plan ever points at prod data before phase 6.
- Latency numbers (cold start, restore, first token) are recorded in the phase-4/6 gate outputs so regressions have a baseline. Tool-call hop latency is not tracked — model latency dominates it.
- Each phase is one or a few dependency-ordered commits on `feat/integrate-sandboxes`, merged to main only when its gate passes — the account-creation dependency for tenancy lands as that branch merges; until then phase 2's tenancy uses the dev-principal mode with the token-to-context seam already shaped for `RequestContext`.

## risks — Risks worth watching

| Risk | Signal | Fallback |
| --- | --- | --- |
| `snapshot_directory`/`mount_image` rough edges (newer API) | Phase-4 restore gate | Full `snapshot_filesystem()` as boot image — isolated behind the lifecycle interface |
| Reaper fails to run (Fly-fleet outage), orphan sandboxes bill on | Modal dashboard sandbox-hours in phase 4/6 | Modal max-lifetime `timeout` plus a long `idle_timeout` as backstops; they kill orphans, losing only that idle period's scratch |
| Reaper race: snapshot vs. a returning turn | Phase-4 race gate | Cancellable reap lease (epoch steal-back); committed snapshots only ever taken from a quiescent box |
| Harness Google provider fix stalls upstream | Phase 3 | Injected-client workaround is already the plan of record; fix is cleanup |
| account-creation branch timing (NO-GO memo) | Phase 2/5 integration | Capability seam works in dev-principal mode; tenancy binding tightens when that branch lands |
