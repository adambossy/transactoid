---
id: assumptions
label: Assumptions & open questions
parent: root
sections: [asked, assumed, open]
crosslinks: [foundation, phase-1a]
---

# Assumptions & open questions

This SmartPlan renders a plan tree decided through brainstorming (design spec dated 2026-06-27). Because the plan was already settled with the user, no new questions were asked while generating the tree — the decisions below were made in that session, and the assumptions are the tactical defaults taken while transcribing it.

## Requirements

- The reader can see every decision the user made, and who made it, in one place.
- The reader can tell which choices were deliberate design decisions and which were tactical defaults taken while writing the plan.
- The reader can see every question still open, so nothing unresolved is hidden.

## asked — What the user decided

| Question | Decision |
| --- | --- |
| Tenancy unit | Household is the tenant; a user belongs to one household |
| Sharing within a household | Some Plaid accounts shared, others private, controlled per account |
| Hard isolation boundary | User-centric RLS, chosen strict-first because tightening later is risky |
| Within-household sharing grain | Per Plaid account, reviving a plaid_accounts table |
| Enforcement | RLS plus app-level filtering, belt-and-suspenders |
| Taxonomy scope | Per-household, seeded from a default |
| Merchant normalization | Global; merchant rules per-household with private-account scoping |
| Joint sessions | Supported, and they see shared-only data |
| Workspace storage | Hybrid: Postgres broker plus R2 blobs, optimistic CAS for atomic writes |
| Phase 1 split | Split into 1a (data model) and 1b (workspace) |
| RLS testing | Postgres marker, skipped when no Postgres URL is set |

## assumed — What was assumed turning it into a tree

| Assumption | Alternative | Why |
| --- | --- | --- |
| Foundation gets its own branch with data-model and workspace sub-pages | Fold into the root | The two decisions are load-bearing for every phase and deserve direct landing pages |
| Phase 1a split into migrations, enforcement, and testing leaves | One long phase-1a page | Keeps each page a quick read and mirrors the real plan's structure |
| Phases 2–6 are one-page leaves under a roadmap hub | A full page tree per phase | They are roadmap stubs, not yet detailed plans |
| Output lives in ~/code/smartplan beside the other generated plans | Inside the transactoid repo | Matches where the tooling and sibling plans already live; can be relocated |

## open — Open questions

- **Clerk versus Auth0** is unresolved and is the first decision in phase 2.
- **Multi-household membership** is deferred; phase 4 signup is where one-household-per-user may need to relax to let a spouse join an existing household.
- **Plaid redirect rearchitecture** may gate phase 5 onboarding for remote deployment.
- **Workspace conflict re-apply** strategy for markdown — three-way merge versus append-only files — is left to the phase 1b plan.
