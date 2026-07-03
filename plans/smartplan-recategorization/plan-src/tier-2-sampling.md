---
id: tier-2-sampling
label: Collect descriptor samples
parent: tier-2
sections: [why-first, the-query, what-it-feeds]
crosslinks: [tier-2-normalizer, tier-2-validation]
---

# Collect descriptor samples

The extraction rules are only as good as our knowledge of the real descriptor formats, which are institution-specific. Before writing any rule, pull the actual corpus from the database.

## why-first — Why this comes first

Guessing the channels (Zelle / Venmo / ATM / processor / direct) up front bakes in blind spots. This pass is discovery: survey a broad swath of real descriptors to find every wrapper and vendor pattern actually present — P2P apps, billers, processors, transfer types, the long tail — so we can pre-define a rule entry for each before writing the normalizer.

## the-query — The query

```sql
SELECT DISTINCT merchant_descriptor, COUNT(*)
FROM plaid_transactions
GROUP BY merchant_descriptor
ORDER BY COUNT(*) DESC;
```

Run it against the `penny-test` Neon branch (real prod-mirrored data), ordered by frequency so the highest-volume patterns surface first.

## what-it-feeds — What it feeds

The sampled descriptors do double duty: they seed the plain-English examples embedded in each [extraction rule](tier-2/normalizer.html), and they become the fixtures for the [eval suite and review page](tier-2/validation.html). Hold a portion back as an unseen eval set so rule changes can be measured for regression.
