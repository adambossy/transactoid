---
id: phase-4-invites
label: Invites
parent: phase-4
sections: [flow, guards, manage]
crosslinks: [phase-4-signup, phase-4-testing]
---

# Invites

"Invite" and "first-login linking" are one mechanism: an invite pre-creates a pending user row that the invitee's signup claims.

## Requirements

- I can invite a family member by email, and when they sign up they land in my household with me instead of getting a separate space.
- I can see everyone I've invited and cancel an invitation I no longer want.
- Inviting someone who already has an account can never hijack or merge accounts — I get a clear explanation instead of a broken outcome.

## flow — The flow

A member posts an email to `/api/invites`. The server creates a **pending users row** in the caller's household (lowercased email, no auth subject yet) and issues a Clerk invitation, which emails the invitee and scopes their signup. When the invitee first logs in, the [resolution order](signup.html) finds the pending row by verified email and links them into that household instead of provisioning a new one.

## guards — Guards

Invites always target the **caller's own household** — the household id is never read from the request. An email that already belongs to an active account (auth subject set) is rejected with a clear "they'll need to start fresh" message: no account takeover, no household merge. Pending rows carry no privileges until claimed, the invitee must verify the same email through Clerk, and re-inviting a pending email is a no-op.

## manage — Managing invites

`GET /api/invites` lists the household's pending invites; `DELETE /api/invites/{email}` revokes one (removes the pending row and the Clerk invitation — never an active user). The frontend invite screen offers enter-an-email, the pending list with revoke, and the already-has-an-account messaging.
