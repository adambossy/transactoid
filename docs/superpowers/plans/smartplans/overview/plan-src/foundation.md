---
id: foundation
label: Foundation decisions
parent: root
sections: [boundary, visibility, what-stays-shared]
crosslinks: [data-model, workspace-storage, phase-1a]
---

# Foundation decisions

The locked decisions from the design spec. Everything in later phases inherits these. They split into two areas: how tenancy and isolation work (the [data model](foundation/data-model.html)), and where per-household files live (the [workspace store](foundation/workspace-storage.html)).

## Requirements

- A household is a hard wall: a member can trust that nothing they do is ever visible to another household.
- Within a household, each spouse controls which accounts are shared and which stay private, account by account.
- When both spouses are present in a shared conversation, only shared information appears — neither person's private data slips in.
- The reader can see, up front, exactly which information is shared across a household and which stays personal.

## boundary — The tenancy boundary

A **household** is the tenant and the hard isolation boundary — nothing ever crosses between households. A **user** belongs to exactly one household (multi-household membership is deferred, not designed out). The hard boundary is enforced as **user-centric row-level security**: the database itself rejects rows from other households and a household member's private rows, on every query.

## visibility — Per-account visibility

Sharing is controlled **per Plaid account**. Each account is owned by a user and is `private` or `shared`. A transaction inherits its account's visibility. The visibility question "what can this user see" resolves to: same household, and (owned by me or shared). A **joint session** — both spouses present — collapses this to shared-only, so neither person's private data enters a shared conversation.

## what-stays-shared — What is shared vs per-household

Not everything is tenant-scoped. Merchant **normalization** is global reference data (names are not sensitive and a shared table normalizes better). Everything else that touches money is per-household: transactions, Plaid items and accounts, tags, sign conventions, Amazon profiles, email receipts, conversations, and agent memory. The category **taxonomy** is per-household, seeded from a default and customizable. Merchant **rules** are per-household, and a rule targeting a private account inherits that account's privacy.
