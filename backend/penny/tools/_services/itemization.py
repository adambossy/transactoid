"""Proportional-allocation helper for transaction itemization.

Used by AmazonMutationPlugin and (future) EmailReceiptMutationPlugin to
distribute a Plaid transaction's total amount across N line items so the
synthetic item amounts sum exactly to the parent's amount_cents.
"""

from __future__ import annotations

from penny.errors import ItemizationError


def proportionally_allocate(
    *, total_cents: int, item_amounts_cents: list[int]
) -> list[int]:
    """Distribute *total_cents* across items proportional to *item_amounts_cents*.

    Uses the largest-remainder (Hamilton) method to ensure the result sums
    exactly to *total_cents*.  Residual cents are distributed to items with the
    largest fractional remainders; ties are broken by descending index (last
    item wins a tie at position 0).

    Args:
        total_cents: Target total to allocate.  Must be >= 0.
        item_amounts_cents: Nominal amounts that define the proportions.
            Must be non-empty.  All values must be >= 0.  If all values are
            zero, equal shares are distributed with any remainder going to the
            last item.

    Returns:
        A list of the same length as *item_amounts_cents* whose values sum
        exactly to *total_cents*.

    Raises:
        ItemizationError: If *item_amounts_cents* is empty, if *total_cents*
            is negative, or if any element of *item_amounts_cents* is negative.
    """
    if not item_amounts_cents:
        raise ItemizationError("item_amounts_cents must not be empty")

    if total_cents < 0:
        raise ItemizationError(f"total_cents must be >= 0; got {total_cents}")

    for idx, amount in enumerate(item_amounts_cents):
        if amount < 0:
            raise ItemizationError(
                f"item_amounts_cents[{idx}] must be >= 0; got {amount}"
            )

    count = len(item_amounts_cents)
    nominal_total = sum(item_amounts_cents)

    if nominal_total == 0:
        # Edge case: all items are zero-priced — distribute evenly.
        per_item = total_cents // count
        remainder = total_cents % count
        result = [per_item] * count
        result[-1] += remainder
        return result

    # Proportional shares as floats.
    shares: list[float] = [
        (amount / nominal_total) * total_cents for amount in item_amounts_cents
    ]

    # Floor each share to get baseline integer allocations.
    floored: list[int] = [int(s) for s in shares]
    residual = total_cents - sum(floored)

    # Fractional parts paired with their original index, sorted largest-first.
    # Stable sort on negative index breaks ties so higher indices win (matching
    # the "last item absorbs residual" invariant when remainders are equal).
    fracs_with_idx = sorted(
        ((shares[idx] - floored[idx], idx) for idx in range(count)),
        key=lambda pair: (pair[0], pair[1]),
        reverse=True,
    )

    for rank in range(residual):
        target_idx = fracs_with_idx[rank][1]
        floored[target_idx] += 1

    return floored
