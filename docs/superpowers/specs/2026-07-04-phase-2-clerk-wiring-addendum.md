# Phase 2 — Real Clerk Wiring Addendum

> Addendum to the [Phase 2 auth spec](2026-07-01-phase-2-auth-social-login-design.md)
> and [plan](../plans/2026-07-02-phase-2-auth-social-login.md). Captures the
> concrete Clerk setup (app id, keys, CLI, frontend SDK) supplied by the user.
> The Phase 2 executor builds the backend against a **mock JWKS** (testable with
> no external service); this addendum is the **post-merge follow-up** that swaps
> the mock for the real Clerk instance and adds the frontend SDK.

## The Clerk application

- **App id:** `app_3G2cQDuqoV52tBPluDb1S0oaBQs` — always pass
  `--app app_3G2cQDuqoV52tBPluDb1S0oaBQs` to `clerk init`.
- Social connection: **Google** (the two allowed users: the owner + spouse).

## Framework note — Penny is Vite + React, NOT Next.js

The vendor instructions assume Next.js. **Ignore every Next.js-specific rule**
(the `@clerk/nextjs` package, `proxy.ts`/`middleware.ts` matcher, async `auth()`,
`ClerkProvider` inside `<body>`). Penny's frontend is Vite + React 19, so:

- Use **`@clerk/clerk-react`** (the JS-frontend / React SDK), not `@clerk/nextjs`.
- `clerk init` full-scaffolds Vite/React; if it defers, follow the JS-frontend
  quickstart: https://clerk.com/docs/js-frontend/getting-started/quickstart
- Components: wrap the app in `<ClerkProvider publishableKey={…}>`; use
  `<SignedIn>` / `<SignedOut>` / `<UserButton>` and **`<SignIn>`** for the
  sign-in surface. **Phase 2 wires `<SignIn>` only; Phase 4 adds `<SignUp>`.**

## Env / config contract (the runtime seam)

- **Frontend (Vite):** `VITE_CLERK_PUBLISHABLE_KEY` — the publishable key
  (safe in client). Read via `import.meta.env`.
- **Backend:** `CLERK_SECRET_KEY` (server-only, never in client) plus the JWT
  verification inputs the Phase 2 backend already consumes from `config.py`:
  the **JWKS URL** and **issuer** of this Clerk instance
  (`https://<frontend-api-domain>/.well-known/jwks.json` and the matching
  issuer). These replace the mock-JWKS fixtures the executor built against —
  no code change beyond pointing config at the real values.
- R2 and Plaid prod values are already in `backend/.env`; the Clerk keys are the
  only ones still to obtain (via the CLI below).

## Setup runbook (interactive — the user runs the login)

Run from `frontend/`:

1. Install/refresh the CLI: `command -v clerk && clerk update --yes` or
   `brew install clerk/stable/clerk` (or `npm i -g clerk`).
2. **`clerk auth login`** — interactive; the *user* completes it in the browser.
   In this session, run it with the `!` prefix: `!clerk auth login`.
3. `clerk init --app app_3G2cQDuqoV52tBPluDb1S0oaBQs` — detects Vite/React,
   installs `@clerk/clerk-react`, writes the publishable key into the frontend
   env, and scaffolds the provider + sign-in controls. It also surfaces the
   secret key + JWKS/issuer for the backend `.env`.
4. `clerk doctor`, then start the app and verify the `<SignIn>` control renders
   and a Google sign-in succeeds.

## Reconciliation with the built backend

- The executor's `<SignIn>`-less backend verifies RS256 JWTs against a
  configurable JWKS. This follow-up sets `PENNY_*`/`CLERK_*` config to the real
  Clerk JWKS/issuer, adds `VITE_CLERK_PUBLISHABLE_KEY` + `@clerk/clerk-react`
  provider/controls in the app, and keeps `<SignUp>` for Phase 4.
- Fail-closed stays: outside dev, missing/invalid Clerk config must refuse
  requests, never fall back to the dev-stub principal.
