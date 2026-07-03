---
id: tier-2-validation
label: Validation, not backfill
parent: tier-2
sections: [no-backfill, dry-run-and-review, iterate]
crosslinks: [tier-2-normalizer, payoff]
---

# Validation, not backfill

We are not doing an automated backfill that repoints historical `derived_transactions.merchant_id`. Confidence that a bulk repoint does the right thing across all history is low, and the cost of silently mismerging counterparties is high. Instead the normalizer applies going forward, gated by a human-in-the-loop review.

## no-backfill — Why no backfill

A bulk repoint is irreversible in practice and easy to get subtly wrong. So the new normalizer affects new syncs only; existing fragmented/collapsed merchants stay as-is. The cleanup benefit accrues to transactions synced after the normalizer ships. This is flagged as a known trade-off, not a surprise — and whether to repoint history later is deferred until the normalizer is proven trustworthy, with validation evidence in hand.

## dry-run-and-review — Dry run and review page

1. **Dry-run pass:** run the new normalizer over a broad sample of existing `plaid_transactions` descriptors with no writes. Record each `descriptor → {normalized_name, display_name, source_channel, counterparty}` and which old `merchant_id`(s) it would collapse or split.
2. **Review HTML page:** a static report walking each proposed transformation, grouped so related descriptors (all candidate "Tania Zelle" sends) sit together, with a checkbox per transformation and room for notes. This surfaces extraction mistakes — wrong counterparty, dropped identity, over-collapse — before anything touches real data.

## iterate — Iterate to acceptance

Iterate on the [rule repository](tier-2/normalizer.html) based on the checked-off results, then re-run the dry run. The page is the acceptance gate for the rule repository, not a migration tool. Alongside it, validate with **evals, not unit tests**: a fixture set of real descriptors with expected `{normalized_name, source_channel, counterparty}`, scored as a suite, with a held-out unseen set so changes are measured for regression. Only once it passes is the normalizer trusted, after which the [combined payoff](../payoff/index.html) lands for new syncs.
