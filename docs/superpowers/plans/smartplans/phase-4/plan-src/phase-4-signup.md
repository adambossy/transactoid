---
id: phase-4-signup
label: Self-serve signup
parent: phase-4
sections: [resolution, auto-provision, bootstrap]
crosslinks: [phase-4-invites]
---

# Self-serve signup

Phase 2 already turns a verified token into a `RequestContext`. Phase 4 changes exactly one branch of that resolution — what happens when the user is unknown.

## resolution — Identity resolution order

On a verified token: (1) resolve by Clerk subject; (2) no match but a **pending invite row** exists for the verified email → claim it and join that household (see [invites](invites.html)); (3) no match, no pending row → **auto-provision** a new solo household. This replaces phase 2's unknown-user 403 — the users table stops being an allowlist and becomes the registry that signup populates.

## auto-provision — Auto-provisioning a solo household

In one idempotent transaction on first sight of an un-invited verified user: create the household (named from the email's local part, editable later), create the user (lowercased email, Clerk subject linked), and seed the household's taxonomy from the default. Workspace prefixes are created lazily by the phase-1b broker on first agent run, so signup stays decoupled from the blob store. A race or retry that finds the row already created is a no-op.

## bootstrap — Frontend bootstrap

After Clerk reports signed-in, the app calls `GET /api/me` — which, because the auth dependency already ran the resolution above, is guaranteed to find a household — and gets back the user, household id, and household name for the header. `PATCH /api/household` renames the household. Clerk's `<SignUp>`/`<SignIn>` handle the actual account creation UI.
