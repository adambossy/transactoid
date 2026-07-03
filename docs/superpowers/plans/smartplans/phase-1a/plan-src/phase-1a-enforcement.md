---
id: phase-1a-enforcement
label: Enforcement
parent: phase-1a
sections: [request-context, set-local, policy, app-filtering]
crosslinks: [data-model, phase-1a-testing]
---

# Enforcement

The two layers that make isolation real, and how the current household reaches the database. The predicate itself is described on the data model page.

## Requirements

- A member's queries only ever return their own household's data, and within it only what they own or what has been shared.
- Even the agent's most open-ended database access cannot reach another household's records or a spouse's private ones.
- A member can never write a record into someone else's household, so data can't be planted where it doesn't belong.

## request-context — Request context

A `RequestContext` carries the user id, household id, and session mode. It travels via a context variable set at the start of each request, so the façade can read it without threading a parameter through fifty methods. In phase 1 a dev-stub resolver builds it from a header or env var; phase 2 swaps that for verified auth with no downstream change.

## set-local — Binding the connection

The façade's session context manager reads the current `RequestContext` and, on Postgres, sets two transaction-local settings: the current household and the current user. These use the transaction-local form so they cannot leak across pooled connections, and a joint session sends the nil-user sentinel. On SQLite the step is skipped.

## policy — The hard backstop

With those settings bound, the RLS policies filter every query at the database — including the agent's unrestricted `run_sql`. This is the property that makes `run_sql` safe in a multi-tenant world: it physically cannot return another household's or a member's private rows, with no change to the tool itself. The policies also carry a write check so a row cannot be written into a foreign household.

## app-filtering — The legible layer

The façade still adds household and visibility predicates to its read methods. This is the suspenders to the RLS belt: it keeps SQLite dev correct where RLS does not run, makes intent obvious to a code reader, and means a single forgotten filter is caught by RLS rather than becoming a breach. See how both layers are [tested](testing.html).
