---
id: phase-2-identity
label: Identity & linking
parent: phase-2
sections: [linking, allowlist]
crosslinks: [phase-2-backend]
---

# Identity & linking

The backend never creates users in phase 2 (provisioning is phase 3, signup is phase 4). It **links** an authenticated Clerk identity to an existing `users` row.

## linking — First-login email linking

On the first authenticated request, verify `email_verified == true` in the token, then link atomically: `UPDATE users SET external_auth_id = :sub WHERE email = :email AND external_auth_id IS NULL RETURNING user_id`. The unique constraint on `external_auth_id` makes the first-login race safe, and a security event is logged when the column is first populated. Emails are normalized to lowercase on both storage and lookup; internationalized addresses are out of scope. Subsequent requests resolve by `external_auth_id` (survives email changes). See how the resolved identity becomes a `RequestContext` in [backend verification](backend.html).

## allowlist — Allowlist = the users table

An authenticated Clerk user whose email/subject matches no `users` row is rejected **403**. This enforces "gated to you and your wife" in our own database, not just at the provider. Clerk's own allowlist is an optional second gate at the signup layer.
