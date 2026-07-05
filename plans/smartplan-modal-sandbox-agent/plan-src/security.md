---
id: security
label: Security model
parent: root
sections: [threat-model, controls, comparisons]
crosslinks: [secrets-proxy, mcp-tools]
---

# Security model

Assume the sandbox is hostile — prompt-injected, running attacker-chosen code. Enumerate what it holds, what it can reach, and why each control is enforced rather than requested. The reap lease and the turn-result callback are two new mechanisms; neither widens the blast radius.

## Requirements

- Full compromise of one conversation's sandbox exposes at most that household's finance data and bounded model spend — never another tenant, a raw credential, or the platform.
- Every capability a sandbox holds can be revoked from the trusted side within one tool or model call.
- No inbound path reaches the sandbox except from our own server, and no outbound path leaves it except to our two endpoints.

## threat-model — What a hostile sandbox holds and where each attack dead-ends

| In the sandbox | Grants | Attack path | Dead-ends because |
| --- | --- | --- | --- |
| MCP capability token | This conversation's tools, this tenant's data | Exfiltrate or abuse tools | Tenancy pinned server-side per request; token is opaque, conversation-scoped, TTL'd, revocable. Ceiling equals what the tenant could do anyway. |
| Proxy capability token | Model calls on this conversation's credential binding | Burn tokens, exfiltrate via prompts to the model | Path allowlist, per-session rate/concurrency limits, kill switch, usage metered to the ledger. No raw key ever present. |
| Turn-result callback token | Write this conversation's turn results to Fly | Post forged/garbage turn results for its own conversation | Conversation-scoped; Fly validates and the endpoint is idempotent by `run_id`. A hostile sandbox can only corrupt its own tenant's turn record — which it already influences by what it streams. No cross-conversation write. |
| Runner ingress token | Nothing outbound — it authenticates Fly to the runner | Useless to the attacker; they already are the runner | Scoped to one sandbox generation; dies with the sandbox. |
| Conversation history plus workspace | The tenant's own conversation data | Already the tenant's; snapshot images live on Modal, fetchable only via our control plane | — |
| No Modal token, no DB URL, no vendor key, no Clerk anything | — | Sandbox cannot create sandboxes, reach Postgres, call vendors directly, or impersonate users | Enforced by absence plus egress pinning. |

Residual risks accepted and named: the agent can still be socially engineered *within* its tenant's authority — e.g. injected content persuading it to run a destructive `run_sql`; that risk exists today and is a tool-policy question (approvals/scoping on the MCP server is the natural future lever). Data the MCP tools legitimately return passes through the sandbox and the model — same as today. gVisor is the isolation boundary between our sandbox and Modal's other tenants; we inherit Modal's posture there.

## controls — The control checklist

- **Inbound**: `inbound_cidr_allowlist` equals Fly egress IPs; runner requires its ingress bearer on every request (tunnel URLs are public-but-unguessable — we do not rely on obscurity, unlike the Cloudflare/Vercel preview-URL default). Modal connect tokens are the documented upgrade if we ever want Modal-verified caller metadata.
- **Outbound**: `outbound_domain_allowlist` equals the proxy Function host plus the Fly MCP host. Network-enforced; blocked TLS attempts are logged to sandbox output, which the relay surfaces into observability.
- **Secrets at rest**: LLM keys in Modal Secrets on the proxy Function; BYO keys stay in the account-creation encrypted vault on Fly, referenced by binding, decrypted only at registration time into the proxy's memory/Dict.
- **Tokens**: all runner-held tokens (ingress, MCP, proxy, turn-result callback) minted per conversation (ingress per sandbox generation), TTL'd, refreshed each turn, revocable centrally; stored hashed on the validating side.
- **Tenancy**: MCP adapter resolves token to `RequestContext` to the same ContextVar-scoped DB session discipline the web routes use; RLS work from the account-creation branch compounds here as defense-in-depth.
- **Observability**: Langfuse tracing continues to work unchanged — the OTEL subscriber attaches to the event stream on Fly (relay side), so sandboxing does not blind tracing; capability grants/revocations and blocked-egress logs become audit events.

## comparisons — Held against the references

- **Cloudflare / Vercel**: we match their strongest shared idea — credential injection at an enforced egress boundary — and their egress-allowlist posture. We differ on ingress: their preview URLs are public-with-obscurity-token by default; our runner requires a bearer and a CIDR match.
- **OpenAI SandboxAgent**: its remote-mount policy is prompt-only; every policy here (egress, tenancy, spend) is enforced off-sandbox. Its serializable reattach-or-rehydrate contract, we implement with Modal snapshots plus the conversation record.
- **sandbox-cli**: we adopt its capability-over-key model and no-key-in-runner proxy, and consciously drop its HMAC body-binding and signed-event-log machinery — proportionate for a first release where the token grants only scoped spend/tool access; its threat analyses (stdout forgery) are moot here because the event channel is a dedicated authenticated stream, never shared stdout.
