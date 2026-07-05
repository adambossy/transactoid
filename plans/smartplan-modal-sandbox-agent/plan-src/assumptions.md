---
id: assumptions
label: Assumptions & open questions
parent: root
sections: [asked, assumed, open-questions]
crosslinks: [mcp-tools, image-bake, turn-lifecycle, event-stream, packaging, secrets-proxy, security, delivery]
---

# Assumptions and open questions

What you decided, what I decided for you, and what neither of us has decided yet.

## asked — What I asked you

| Question | Your answer | Where it shaped the plan |
| --- | --- | --- |
| How does the sandboxed agent reach the finance DB? | All tools over an MCP server — Postgres accessed via MCP | Tools over MCP; also the thin-image win on Image bake |
| Sandbox identity unit? | Per conversation | Turn lifecycle (one snapshot per conversation, per-conversation lock) |
| Codebase baseline? | On top of feat/account-creation | Tenancy binding, billing-gate credential selection, usage ledger hooks throughout |
| Migration scope? | Chat turns only | Cron/scheduled reports stay on the Fly ephemeral-machine contract; Delivery phase 5 touches only /api/chat |

Plus four constraints you set in the brief, treated as fixed: Fly relays the stream (browser never talks to the sandbox); whole-turn replay is acceptable on disconnect; 15-minute idle snapshot-plus-teardown with exactly one snapshot per sandbox; a new top-level package plus deployable, cleanly segregated, with a baked Modal image.

## assumed — What I assumed without asking

| Assumption | Alternative | Why this default | Affects |
| --- | --- | --- | --- |
| Fly *pulls* events from a runner HTTP server over a Modal tunnel | Runner pushes to a Fly callback; or exec-stdout wire | Exec streams can't re-attach; pull keeps retry/auth logic on the trusted side; matches Vercel/Cloudflare reattach patterns | Event stream |
| Harness events cross the wire; translation stays on Fly | Runner emits AI SDK frames directly | bridge.py and persistence stay website-domain and unchanged in role; codec is the smaller new artifact | Event stream, Packaging |
| Lazy snapshot at idle-reap plus a runner-to-Fly turn-result callback per turn | Eager snapshot after every turn | Fewer Modal calls, no per-turn snapshot coordinator, and the committed snapshot stays quiescent so the torn-snapshot problem disappears; the callback makes each completed turn durable, so lazy's only exposure is ephemeral scratch. One snapshot per sandbox still holds — each reap replaces the last | Turn lifecycle |
| `snapshot_directory('/workspace')` plus `mount_image`, not full-filesystem snapshots | `snapshot_filesystem()` as next boot image | Smaller deltas, base image upgradable independently; fallback isolated behind the lifecycle interface | Image bake |
| Bearer capability tokens without HMAC body-binding | sandbox-cli's signed-request envelope | Tokens grant only scoped spend/tool access over TLS; proportionate first release, upgradeable later | Secrets proxy, Security |
| System prompt rendered on Fly, shipped in the turn payload | Render in the runner | Rendering needs schema/taxonomy/memory (trusted data plus finance deps); keeps the runner penny-free | Turn lifecycle, Image bake |
| R2 per-turn workspace checkout (account-creation phase 1b) is *replaced* by sandbox snapshots for chat turns | Keep R2 as the workspace source of truth, snapshot as cache | Two durability layers for one workspace invites drift; snapshots are the simpler single owner. R2 stays for reports/artifacts | Turn lifecycle |
| Amazon plugin toolset goes over MCP like the core tools | Run it in-sandbox | Login profiles/scraping sessions are credential-adjacent; consistent with all tools via MCP | Tools over MCP |

## open-questions — Decisions from review, deferrals, and what's still open

### Decided in review

- **Reaper deployment: a Fly cron job.** The idle reaper runs as a scheduled Fly cron sweep — a `penny` CLI subcommand invoked on a schedule, consistent with the existing cron-manager contract — not an in-process web task. Fleet-safety still comes from the row-locked reap lease. See Turn lifecycle.
- **Stop/interrupt: an explicit cancel endpoint.** A user "stop" routes through Fly to `POST /runs/{run_id}/cancel` on the runner, which aborts the in-flight run. In scope, added in Delivery phase 5. See Event stream.

### Settled

- **Tool-call latency is not a concern.** Model latency dominates the sandbox-to-Fly tool-call hop, so the added hop is not treated as a measured gate.
- **Snapshot storage cost is zero today.** Modal does not currently charge for snapshot image storage, so keeping one delta per conversation carries no fleet-scale cost.

### Deferred / out of scope

- **Approvals and elicitation** are out of scope for this change. The versioned `POST /turns` payload keeps them addable later without a redesign.
- **Memory snapshots** are out of scope for now and planned once Modal ships non-expiring sandbox memory snapshots; adoption is additive (see the Image bake cold-start budget).

### Still open

- **Plaid Link's localhost flow.** `connect_new_account` runs a localhost HTTPS server plus browser today and only works with the backend on the user's machine; over MCP-from-a-sandbox it needs the hosted-link rearchitecture (account-creation added a hosted Plaid link-token tool — confirm it fully supersedes the localhost flow before the cutover). Affects Tools over MCP.
