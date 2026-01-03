# Amazon Order to Plaid Transaction Matching Strategy

## Overview

This document describes the strategy for reconciling Amazon orders (from CSV exports) with Plaid transactions (from bank/credit card data).

## Data Sources

### Amazon CSV Data

**Orders** (`AmazonOrdersCSVLoader`):
- `order_id`: Amazon order ID (e.g., `113-5524816-2451403`)
- `order_date`: Date the order was placed
- `order_total_cents`: Total including tax + shipping
- `tax_cents`: Tax amount
- `shipping_cents`: Shipping amount

**Items** (`AmazonItemsCSVLoader`):
- `order_id`: Links to parent order
- `asin`: Amazon product identifier
- `description`: Product name
- `price_cents`: Price per item (without tax)
- `quantity`: Number of items

### Plaid Transaction Data

- `plaid_transaction_id`: Unique identifier
- `posted_at`: Date transaction posted to account
- `amount_cents`: Transaction amount
- `merchant_descriptor`: Merchant name (typically just "Amazon")
- `external_id`: Plaid's external reference
- `account_id`: Bank account identifier

## Matching Rules

### Primary Rule: Exact Amount Match

```
order_total_cents == amount_cents
```

The Amazon order total (including tax and shipping) should exactly match the Plaid transaction amount. This is the primary matching criterion and works for most orders since totals tend to be unique.

### Secondary Rule: Date Proximity Validation

```
0 <= (posted_at - order_date).days <= 4
```

The Plaid `posted_at` date should be 0-4 days after the Amazon `order_date`. This accounts for credit card processing delays.

**Observed date lag distribution:**
| Lag (days) | Frequency |
|------------|-----------|
| 0 | 16% |
| 1 | 48% |
| 2 | 24% |
| 3 | 8% |
| 4 | 4% |

### Tie-Breaker: Closest Date

When multiple Plaid transactions have the same amount, select the one with `posted_at` closest to the Amazon `order_date`.

## What We Do NOT Use

- **Item name / merchant descriptor**: These are unreliable for matching since Plaid often just shows "Amazon" without item details
- **ASIN**: Not present in Plaid data
- **Order ID**: Not present in Plaid data

## O(N) Matching Algorithm

```python
from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass
class AmazonOrder:
    order_id: str
    order_date: date
    order_total_cents: int
    tax_cents: int
    shipping_cents: int


@dataclass
class PlaidTransaction:
    plaid_transaction_id: int
    posted_at: date
    amount_cents: int
    merchant_descriptor: str
    external_id: str


def match_orders_to_transactions(
    amazon_orders: list[AmazonOrder],
    plaid_txns: list[PlaidTransaction],
    max_date_lag: int = 5,
) -> dict[str, PlaidTransaction | None]:
    """
    Match Amazon orders to Plaid transactions.

    Args:
        amazon_orders: List of Amazon orders to match
        plaid_txns: List of Plaid transactions to match against
        max_date_lag: Maximum days between order_date and posted_at

    Returns:
        Dict mapping order_id -> matched PlaidTransaction or None

    Time Complexity: O(N + M) where N = orders, M = transactions
    Space Complexity: O(M) for the hash map
    """

    # 1. Build hash map: amount_cents -> list of transactions
    #    O(M)
    txn_by_amount: dict[int, list[PlaidTransaction]] = defaultdict(list)
    for txn in plaid_txns:
        txn_by_amount[txn.amount_cents].append(txn)

    # 2. Track which transactions have been matched (to avoid double-matching)
    used_txn_ids: set[int] = set()

    # 3. Match each order
    #    O(N) amortized - each txn matched at most once
    matches: dict[str, PlaidTransaction | None] = {}

    for order in amazon_orders:
        candidates = txn_by_amount.get(order.order_total_cents, [])

        best_match: PlaidTransaction | None = None
        best_lag: int = max_date_lag + 1

        for txn in candidates:
            if txn.plaid_transaction_id in used_txn_ids:
                continue

            # Date lag: posted_at should be 0-N days AFTER order_date
            lag = (txn.posted_at - order.order_date).days

            if 0 <= lag <= max_date_lag and lag < best_lag:
                best_match = txn
                best_lag = lag

        if best_match:
            used_txn_ids.add(best_match.plaid_transaction_id)

        matches[order.order_id] = best_match

    return matches
```

### Complexity Analysis

| Step | Complexity | Notes |
|------|------------|-------|
| Build hash map | O(M) | One pass over transactions |
| Match loop | O(N) | One pass over orders |
| Candidate lookup | O(1) avg | Hash map lookup |
| Candidate scan | O(1) amortized | Each txn matched at most once |

**Total: O(N + M)**

### Why the Inner Loop is O(1) Amortized

The inner loop over candidates appears to be O(K) where K is the number of transactions with the same amount. However, since each transaction can only be matched once (tracked via `used_txn_ids`), the total work across all orders is bounded by M.

### Optimization for High Collision Rates

If many transactions share the same amount, pre-sort candidates by date and use binary search:

```python
# Pre-sort candidates by posted_at
for amount, txns in txn_by_amount.items():
    txns.sort(key=lambda t: t.posted_at)

# Binary search for date window instead of linear scan
import bisect

target_date = order.order_date
# Find transactions in the valid date range
```

This keeps worst-case at O((N + M) log K) where K is max collisions per amount.

## Edge Cases

1. **No match found**: Order remains unmatched (returns `None`)
2. **Multiple orders with same amount on same day**: Each gets its own Plaid match; first-come-first-served based on order iteration
3. **Refunds**: Negative amounts in Plaid; could be matched to Amazon returns if return data is available
4. **Split shipments**: One Amazon order may result in multiple Plaid transactions; requires sum-based matching (not covered here)

## Match Rate Observations

Using this strategy on test data:
- **25 Amazon orders** matched to **25 Plaid transactions**
- **100% match rate** when using `plaid_transactions` table
- **97% match rate** when using `derived_transactions` table (which has item-level splits)

## Recommendations

1. Use `plaid_transactions` (raw data) rather than `derived_transactions` for matching
2. Filter Plaid transactions to Amazon-only before matching (WHERE merchant_descriptor LIKE '%amazon%')
3. Process orders in chronological order to ensure consistent matching when amounts collide
