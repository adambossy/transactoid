---
id: verification
label: End-to-end verification
parent: root
sections: [approach, happy-path, tool-call, cancellation, persistence, exit-criteria]
crosslinks: [turn-lifecycle, event-stream, mcp-tools, delivery]
---

# End-to-end verification

Before the sandbox path becomes the default, four end-to-end scenarios must pass against a real browser driving the full stack — browser, Fly, Modal sandbox, MCP tools, and the secrets proxy. These are the acceptance tests for the cutover; nothing flips to sandboxed-by-default until all four are green.

## Requirements

- After sandboxes ship, a real user can open a new chat, send a message, and get a normal streamed answer served from inside a sandbox.
- A message that needs the user's financial data returns correct results, proving tools actually run and stay scoped to that one user.
- A user can stop a long answer mid-flight and it truly stops — the run ends and model spend stops, not just the visible stream.
- A user can close the app and reopen it later to find the conversation and its answers intact.

## approach — How these run

The four scenarios are driven as real browser tests (Playwright, alongside the existing `frontend/e2e/*` specs) against a dev stack pointed at the `penny-test` Neon branch and a dev Modal environment, with `PENNY_SANDBOX_TURNS` on. Each scenario asserts at every hop, not just in the browser:

- **Browser** — the AI SDK frames the user actually sees (text deltas, tool parts, finish).
- **Fly** — the conversation record state machine (`IDLE`/`ACTIVE`/`REAPING`/`TERMINATED`), persisted messages, the turn-result callback, capability-token mint and revoke.
- **Modal** — sandbox created/reused/terminated (via tags plus `Sandbox.list`), tunnel resolved.
- **Proxy** — model calls arrived with a capability token and the usage report landed on the ledger.

Each scenario names a concrete, observable pass condition so "it worked" is evidence, not assertion — the same bar the Delivery gates hold.

## happy-path — Scenario 1: new conversation, served by a sandbox

**Intent:** the cold path works end to end. This is the fresh-turn flow on the Turn lifecycle page.

Steps: open the app signed in; start a new conversation; send a plain message that needs no tool this turn (a greeting or a general question).

Assert:

- A **fresh Modal sandbox** is created for this conversation — the conversation record gains `sandbox_id` and `tunnel_url`, and the sandbox is tagged with the conversation id.
- The turn runs **inside the sandbox**: the harness loop's events arrive over the tunnel and are relayed to the browser as normal AI SDK frames; the user sees a streamed answer indistinguishable from today.
- On completion the conversation transitions back to `IDLE` and the runner's **turn-result callback** has fired (Tier 2 persisted).
- The web process ran no agent loop itself — with the flag on, the in-process path is never exercised.

## tool-call — Scenario 2: a message that invokes a tool

**Intent:** tools execute over MCP on the trusted side, tenant-scoped, with their events surfaced.

Steps: in the same conversation, send a message that forces a tool — e.g. "show my five largest transactions," which drives `run_sql`.

Assert:

- The browser receives a **`tool-input-available`** then a **`tool-output-available`** frame for the tool, and a correct final answer built from real `penny-test` data.
- The tool executed **on Fly via the MCP server**, not in the sandbox: the MCP request carried the conversation's **capability token**, resolved to the right `RequestContext`, and `run_sql` ran under that tenant — a row from another household is never returned.
- The **sandbox held no DB credential** and made no direct outbound DB or vendor connection; the egress allowlist shows only the proxy and MCP hosts.
- The tool's `ToolExec*` events round-tripped through the relay like any other event, so start/finish/error render normally.

## cancellation — Scenario 3: cancel a running turn mid-flight

**Intent:** stop actually stops the remote run, not just the visible stream.

Steps: send a message that produces a long, multi-step answer; while it is still streaming, click **stop** in the UI.

Assert:

- The browser's stop issues **`POST /runs/{run_id}/cancel`** (through Fly to the runner); the runner aborts the harness run and flushes a terminal event to the log.
- The SSE stream to the browser **closes cleanly** — no error banner, the partial answer stays visible — and the conversation returns to `IDLE`.
- **Model spend stops:** no further model calls reach the proxy after the cancel; the proxy's per-run usage stops advancing.
- The partial turn persists coherently — Tier 1 frames up to the cancel, and the turn-result callback records a cancelled/partial outcome — so a reload shows the same partial answer, not a phantom "still running" state.
- The sandbox itself stays healthy and reusable for the next turn: cancel aborts the run, not the box.

## persistence — Scenario 4: close, reopen, resume the conversation

**Intent:** completed turns and their workspace survive the user leaving. This exercises the warm, restore, and durability paths together.

Steps: complete one or more turns; **close the browser tab**; reopen the app and open the same conversation. Run it twice — once immediately (warm) and once after the 15-minute idle window (reaped).

Assert:

- On reopen, the conversation **rehydrates from persisted state**: `GET /api/sessions/{id}` returns the full transcript built from Tier-1 frames plus Tier-2 turn results, and every prior answer is present and correct.
- **Within the idle window:** the next message **reuses the warm sandbox** — same `sandbox_id`, no cold start.
- **After the reaper ran:** the conversation is `TERMINATED` with a `snapshot_image_id`; the next message **cold-restores** a fresh sandbox via `mount_image`, and any workspace file a prior turn wrote is present.
- A crash-injection variant — kill the sandbox mid-idle before the next turn — loses **no completed turn**, because results were persisted by the callback, not the snapshot.

## exit-criteria — Exit criteria

The cutover (the flag-default flip in Delivery phase 6) is gated on all four scenarios passing in CI against `penny-test` plus dev Modal, together with the observability checks: Langfuse traces show the full turn end to end, and capability grants/revocations plus any blocked-egress attempts appear as audit events. A single red scenario blocks the flip.
