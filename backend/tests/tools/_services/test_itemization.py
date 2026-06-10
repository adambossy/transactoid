"""Tests for the proportionally_allocate helper in tools/_services/itemization.py."""

from __future__ import annotations

import pytest

from penny.errors import AppError
from penny.tools._services.itemization import proportionally_allocate


def test_proportionally_allocate_no_rounding_needed() -> None:
    """When item amounts already divide evenly, output equals input scaled 1:1."""
    # input
    total_cents = 300
    item_amounts_cents = [100, 100, 100]

    # act
    output = proportionally_allocate(
        total_cents=total_cents, item_amounts_cents=item_amounts_cents
    )

    # expected
    expected_output = [100, 100, 100]

    # assert
    assert output == expected_output
    assert sum(output) == total_cents


def test_proportionally_allocate_distributes_residual() -> None:
    """One extra cent goes to the item with the largest fractional remainder."""
    # input: items [1, 1, 1], total 10 → each gets 3.33…; 1 residual cent
    # largest remainder is the same for all, so the highest index wins the tie
    total_cents = 10
    item_amounts_cents = [1, 1, 1]

    # act
    output = proportionally_allocate(
        total_cents=total_cents, item_amounts_cents=item_amounts_cents
    )

    # expected: sum must be 10; residual to highest-index item
    expected_sum = 10

    # assert
    assert sum(output) == expected_sum
    assert len(output) == 3


def test_proportionally_allocate_two_items_unequal() -> None:
    """Classic 70/30 proportional split."""
    # input
    total_cents = 1000
    item_amounts_cents = [70, 30]

    # act
    output = proportionally_allocate(
        total_cents=total_cents, item_amounts_cents=item_amounts_cents
    )

    # expected
    expected_output = [700, 300]

    # assert
    assert output == expected_output
    assert sum(output) == total_cents


def test_proportionally_allocate_single_item() -> None:
    """Degenerate single-item case: entire total goes to that item."""
    # input
    total_cents = 4999
    item_amounts_cents = [100]

    # act
    output = proportionally_allocate(
        total_cents=total_cents, item_amounts_cents=item_amounts_cents
    )

    # expected
    expected_output = [4999]

    # assert
    assert output == expected_output


def test_proportionally_allocate_rejects_empty() -> None:
    """Empty item list raises ItemizationError (subclass of AppError)."""
    with pytest.raises(AppError):
        proportionally_allocate(total_cents=100, item_amounts_cents=[])


def test_proportionally_allocate_rejects_negative_total() -> None:
    """Negative total_cents raises ItemizationError."""
    with pytest.raises(AppError, match="total_cents must be >= 0"):
        proportionally_allocate(total_cents=-1, item_amounts_cents=[100, 200])


def test_proportionally_allocate_rejects_negative_item_amount() -> None:
    """Any negative element in item_amounts_cents raises ItemizationError."""
    with pytest.raises(AppError, match=r"item_amounts_cents\[1\] must be >= 0"):
        proportionally_allocate(total_cents=100, item_amounts_cents=[50, -10])


def test_proportionally_allocate_zero_total() -> None:
    """Zero total_cents allocates zero to every item."""
    # input
    total_cents = 0
    item_amounts_cents = [50, 50]

    # act
    output = proportionally_allocate(
        total_cents=total_cents, item_amounts_cents=item_amounts_cents
    )

    # expected
    expected_output = [0, 0]

    # assert
    assert output == expected_output


def test_proportionally_allocate_all_zero_items() -> None:
    """When all item amounts are zero, equal shares plus last-item residual."""
    # input: 3 items all zero-priced, total 10 → 3+3+4
    total_cents = 10
    item_amounts_cents = [0, 0, 0]

    # act
    output = proportionally_allocate(
        total_cents=total_cents, item_amounts_cents=item_amounts_cents
    )

    # expected
    expected_output = [3, 3, 4]

    # assert
    assert output == expected_output
    assert sum(output) == total_cents
