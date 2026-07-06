---
id: secrets-proxy
label: Secrets proxy
parent: architecture
sections: [proxy-design, capability-registration, provider-routing, egress]
crosslinks: [assumptions, security, mcp-tools]
---

# The secrets proxy

A Modal Function that holds the LLM keys and injects them at the egress boundary. The sandbox authenticates with a conversation-scoped capability token and never sees a real credential.

## Requirements

- The agent's model calls work and stream exactly as if it held the API key, with no perceptible added latency.
- Someone who fully controls a sandbox can spend model tokens only for that one conversation, within its billing limits, and can be cut off instantly.
- Which key gets used (platform key vs a user's own key) is decided by the billing gate on the trusted side, never by anything in the sandbox.

## proxy-design — Design

A deployed Modal app: `@app.function(secrets=[...])` plus `@modal.asgi_app()` running a small FastAPI reverse proxy with `@modal.concurrent` for parallel streams. Request pipeline (sandbox-cli's auth-gate chain, simplified):

- **Path allowlist** — only the model-API routes we use (e.g. Gemini `generateContent`/`streamGenerateContent`, Anthropic `/v1/messages`). Everything else 404s.
- **Capability check** — `Authorization: Bearer <proxy token>`, constant-time lookup against the session registry; unknown/expired/revoked to 401.
- **Key injection and forward** — strip the bearer, attach the real key from the registered credential binding, stream the upstream response back (SSE passthrough; a started streaming response is exempt from Modal's 150 s first-byte cap).
- **Usage accounting** — token usage from the response rides back to Fly (async report keyed by conversation) to feed the usage ledger from the account-creation branch.

Rejected alternatives: keys in the sandbox env (the thing we are here to eliminate); Modal's Caddy-sidecar credential-injection recipe (right idea, but sidecars are experimental and per-sandbox); routing LLM traffic through Fly (adds our web server to every token's path — the dedicated Function scales and fails independently).

## capability-registration — Capability registration (control plane)

Fly is the proxy's only administrator. An admin API on the same Function (separate path, protected by Modal's `requires_proxy_auth` — Modal-Key/Modal-Secret headers only Fly holds):

- `register_session(conversation_id, token_hash, credential_ref, limits, ttl)` — called at turn start after the billing gate decides *which* credential applies (platform subsidy key vs the household's BYO key from the encrypted vault). The proxy stores the binding in memory backed by a Modal Dict, so a cold-started proxy container can rehydrate.
- `revoke_session(conversation_id)` — kill switch; also implicit via TTL expiry, refreshed each turn like the MCP token.
- Per-session limits (requests/minute, max concurrent streams) enforced at the proxy — the sandbox-side agent can retry, but it cannot spend unboundedly.

This is sandbox-cli's v2 `LocalProxyBroker` shape (runner holds no key; registration is one admin call per session) with Cloudflare/Vercel's injection-at-egress mechanics, minus the HMAC body-binding — a bearer capability over TLS is proportionate here because the token grants only scoped LLM spend, not data access. Recorded as an explicit simplification on the Assumptions page.

## provider-routing — Provider routing (and the Google gap)

The runner points the harness model provider at the proxy instead of the vendor:

- **Anthropic / OpenAI providers**: pass `base_url=<proxy>` — both providers apply it to their SDK clients. The capability token rides as the API key value, which the proxy strips and replaces.
- **Google/Gemini (Penny's current model): the harness has a real gap** — `GoogleProvider` accepts `base_url` but silently never applies it to the SDK client it builds. The runner therefore constructs the `genai` client itself (`http_options` pointed at the proxy) and injects it via the provider's `client=` override. File the one-line upstream fix in agent-harness in parallel; the workaround is deleted when it lands.

The proxy normalizes nothing — it is vendor-path-passthrough, so adding a provider is a path-allowlist entry and a credential binding, not a protocol adapter.

## egress — Egress pinning

The sandbox is created with `outbound_domain_allowlist` equal to exactly two hosts: the proxy Function's domain and Fly's MCP host. Everything else — including the real vendor APIs — is blocked at the network layer, so even a leaked real key inside the sandbox could not be exercised from there. Two caveats to verify in the delivery phases:

- The domain allowlist covers TLS/443 only (SNI-matched, beta). Non-TLS egress needs no allowance here — nothing the runner does is non-TLS — but the hardening phase should confirm blocked-traffic logging behaves as documented.
- This is *enforced* policy, deliberately: the OpenAI SandboxAgent comparison showed prompt-level-only policy is the weak spot. Ours is a network rule, not a system-prompt request.
