---
id: mcp-tools
label: Tools over MCP
parent: architecture
sections: [toolset-split, server, tenancy-auth]
crosslinks: [security, secrets-proxy]
---

# Tools over MCP

Every finance tool executes on Fly behind an MCP server; the sandboxed agent is just an MCP client. The database credential never leaves the trusted side, and the sandbox image drops the entire finance stack.

## Requirements

- The agent's tools behave identically to today from the model's point of view — same names, same schemas, same results.
- A tool call can only ever touch the data of the household that owns the conversation, enforced where the tool runs, not where it is called from.
- A stolen tool-access token is useless for any other conversation and dies when revoked or expired.

## toolset-split — Which toolsets go where

| Toolset | Runs | Why |
| --- | --- | --- |
| Core finance tools (`run_sql`, sync, categorizer, reports) | Fly, via MCP | They need the DB, Plaid, R2 — all trusted-side credentials and code. |
| Amazon plugin toolset | Fly, via MCP | Scraping sessions and login profiles are secrets-adjacent; same treatment. |
| `FilesystemTools` | Sandbox, local | The whole point of the sandbox: unrestricted file work in `/workspace`, snapshot-persisted. |
| Skills toolset | Sandbox, local | Skills are prompt-plus-script bundles executing in the workspace; baked into the image. |

The harness composes this without new machinery: the runner constructs the `Agent` with `[MCPServerHTTP(url, auth), FilesystemTools(sandbox=local), skills_toolset]` — an MCP server already satisfies the harness `Toolset` protocol, and tool identity is preserved because the MCP server exports the same tool names and JSON schemas the `@tool` wrappers declare today.

## server — The MCP server on Fly

agent-harness is MCP *client*-only, so the server side is new code using the standard `mcp` Python SDK (streamable-HTTP transport), mounted on the existing FastAPI app — same Fly deployable, new path (e.g. `/mcp`). It is a thin adapter, not a new tool system:

- It enumerates the existing toolsets (`build_toolset()`, `build_amazon_toolset()`) and exposes each harness `Tool` as an MCP tool — schema passthrough, `structured_content` to MCP `structuredContent` (the convention the bridge already speaks).
- Domain placement respects the hard constraints: the adapter imports agent-domain tools (website to agent, the allowed direction) and website auth; tools import nothing new. It is a peer of `api/bridge.py` — a second seam where the website hosts the agent's machinery.
- Tool *events* (start/end, errors) still reach the user's stream because the harness loop in the sandbox emits `ToolExec*` events around each MCP call exactly as it does for local tools — the relay carries them like any other event.

## tenancy-auth — Tenancy and auth

Auth is a per-conversation **MCP capability token**, minted by Fly at turn start and supplied to the harness client via its per-connect `AuthHandler` hook (so rotation needs no runner restart):

- Token to server-side record: `{conversation_id, household_id, user_id, session_mode, expiry}`. Opaque token, constant-time lookup; no claims to forge.
- On every MCP request, the adapter resolves the token and pins the request-scoped tenancy context (`RequestContext` plus the ContextVar re-pin, the same seam the account-creation branch threads through `stream_and_persist`). `run_sql` and friends then execute under that tenant exactly as a web-originated call would.
- Expiry is turn-scoped-plus-grace; Fly refreshes the record each turn. Revocation equals delete the record — an abandoned or compromised sandbox loses tool access at the next call.

**Blast-radius statement** (the point of the whole design): a fully hostile agent — prompt-injected, arbitrary code in the sandbox — can call exactly the tools this conversation's tenant could call anyway, against that tenant's data only. It cannot reach the database, other tenants, the LLM keys, or the Modal control plane. See the Security model page for what it *can* still do.
