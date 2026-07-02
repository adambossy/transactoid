---
id: phase-2-backend
label: Backend verification
parent: phase-2
sections: [verify, request-context, auth-mode, cors]
crosslinks: [phase-2-identity, phase-2-conversations]
---

# Backend verification

A FastAPI dependency (composes per-route, easy to test) turns a bearer token into a phase-1a `RequestContext`. Identity resolution is on the [identity page](identity.html).

## verify — JWT verification

Extract `Authorization: Bearer`. Verify against Clerk's JWKS: signature, `iss` against a hardcoded expected value, `exp` with 60s skew, audience if set. Reject `alg=none` / alg-confusion. Missing/invalid → **401**; unknown user → **403**. The **JWKS URL comes from config, never from the token's `iss`** (closes an SSRF hole); cache with a ~15-minute TTL and force-refresh on a verification miss (key rotation).

## request-context — Building the context

Build `RequestContext` and set the phase-1a ContextVar, resetting in `finally`. **`user_id`/`owner_user_id` come only from the verified token, never the request body.** `session_mode` is read from the conversation row ([conversation scoping](conversations.html)), defaulting to individual for non-conversation routes. From here phase 1a's `SET LOCAL` + RLS enforce isolation unchanged, including over the now read-only `run_sql`.

## auth-mode — Fail-closed auth mode

`PENNY_AUTH_MODE` defaults to `clerk`. Startup **fails closed** if the value is invalid or clerk-mode config is missing. In clerk mode the dev-stub path is **unreachable** — no header fallback. In dev mode the stub accepts only an env-pinned principal (never arbitrary `X-Penny-*` headers) and logs a loud warning.

## cors — CORS lockdown

Tighten from `["*"]` to `[PENNY_FRONTEND_ORIGIN, http://localhost:5173]` with `allow_credentials=True`, scoped methods/headers. `PENNY_FRONTEND_ORIGIN` is required in clerk mode; never `*` with credentials.
