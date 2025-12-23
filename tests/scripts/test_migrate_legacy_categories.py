from __future__ import annotations

import pytest

from scripts import migrate_legacy_categories as mlc


def create_legacy_category(
    code: str,
    *,
    parent_code: str | None = None,
    sort_order: int | None = None,
) -> mlc.LegacyCategory:
    return mlc.LegacyCategory(
        code=code,
        display_name=code,
        parent_code=parent_code,
        is_active=True,
        sort_order=sort_order,
    )


def test_slugify_label_handles_special_characters() -> None:
    # input
    label = "Banking Movements (Transfers, Refunds & Fees)"

    # act
    slug = mlc.slugify_label(label)

    # expected / assert
    assert slug == "banking_movements_transfers_refunds_fees"


def test_build_slug_map_deduplicates_collisions() -> None:
    # input
    categories = [
        create_legacy_category("Other"),
        create_legacy_category("Other!"),
    ]

    # act
    slug_map = mlc.build_slug_map(categories)

    # expected / assert
    assert slug_map["Other"] == "other"
    assert slug_map["Other!"] == "other_2"


def test_build_category_rows_orders_and_links_children() -> None:
    # input
    categories = [
        create_legacy_category("Income", sort_order=0),
        create_legacy_category("Salary & Wages", parent_code="Income", sort_order=1),
        create_legacy_category("Food & Dining", sort_order=2),
        create_legacy_category(
            "Groceries", parent_code="Food & Dining", sort_order=200
        ),
    ]
    slug_map = mlc.build_slug_map(categories)

    # act
    rows, mapping = mlc.build_category_rows(categories, slug_map)

    # expected
    expected_keys = [
        "income",
        "income.salary_wages",
        "food_dining",
        "food_dining.groceries",
    ]

    # assert
    assert [row["key"] for row in rows] == expected_keys
    assert mapping["Groceries"] == "food_dining.groceries"
    assert rows[1]["parent_key"] == "income"


def test_build_category_rows_raises_for_missing_parent() -> None:
    # input
    categories = [
        create_legacy_category("Groceries", parent_code="Food & Dining"),
    ]
    slug_map = mlc.build_slug_map(categories)

    # act / assert
    with pytest.raises(ValueError):
        mlc.build_category_rows(categories, slug_map)
