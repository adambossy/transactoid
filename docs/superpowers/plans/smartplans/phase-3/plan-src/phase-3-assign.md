---
id: phase-3-assign
label: Assignment & handoff
parent: phase-3
sections: [interactive, reparent, handoff]
crosslinks: [phase-3-schema, phase-3-safety]
---

# Assignment & handoff

Who owns each account, how visible it is, and how the two of you take ownership after the data has moved.

## Requirements

- I decide, for each account, who owns it and whether it is private or shared, one account at a time.
- Every one of my legacy transactions ends up attached to the right owner and household, with none left unassigned.
- After the move, my wife and I each sign up normally and land in the shared household with our accounts already owned correctly.

## interactive — Interactive account assignment

The tool lists each linked account — institution, name, and a few sample transactions for recognition — and prompts for owner (you or your wife) and visibility (private or shared). Every choice is appended to a mapping record file as it is made, so a re-run resumes rather than re-prompting, and the assignment is auditable after the fact.

## reparent — Re-parenting the data

Using the mapping, the re-parent stage sets owner, household, and visibility on each Plaid item and account, and denormalizes those onto every child transaction and item; household-only tables like categories and tags are assigned to the household. A post-condition query asserts that **zero rows remain with an unassigned tenant column** across all scoped tables — the stage fails loudly otherwise, so nothing slips through before the not-null and row-level-security contract is enforced.

## handoff — Pending-user signup handoff

Bootstrap seeds the household plus two pending user rows — your email and your wife's — with no login attached yet. You each then sign up through the normal Phase-4 flow, and first-login linking matches your verified email to the pending row and claims it. You land in the migrated household with your assigned accounts already owned correctly; your wife lands in the same household seeing her accounts and shared ones, never your private accounts. It reuses the invite-and-link mechanism exactly. Next: [safety and validation](safety.html).
