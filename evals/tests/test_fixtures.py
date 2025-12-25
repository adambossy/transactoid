from __future__ import annotations

import yaml

from evals.data.fixtures import FIXTURES
from evals.data.test_db_builder import EvalDBBuilder
from services.db import Base, CategoryRow, DB
from services.taxonomy import Taxonomy


def _create_db() -> DB:
    """Create in-memory database instance for testing."""
    db = DB("sqlite:///:memory:")
    with db.session() as session:
        assert session.bind is not None
        Base.metadata.create_all(session.bind)
    return db


def _load_full_taxonomy(db: DB) -> Taxonomy:
    """Load full taxonomy from configs/taxonomy.yaml."""
    with open("configs/taxonomy.yaml") as f:
        data = yaml.safe_load(f)

    categories = []
    for idx, cat_data in enumerate(data["categories"], start=1):
        categories.append(
            CategoryRow(
                category_id=idx,
                parent_id=None,  # Will be set correctly by taxonomy loader
                key=cat_data["key"],
                name=cat_data["name"],
                description=cat_data.get("description"),
                parent_key=cat_data.get("parent_key"),
            )
        )

    db.replace_categories_rows(categories)
    return Taxonomy.from_db(db)


def test_last_month_spending_fixture_builds_correctly() -> None:
    """Test last_month_spending fixture populates DB with correct totals."""
    # Setup
    db = _create_db()
    taxonomy = _load_full_taxonomy(db)
    fixture = FIXTURES["last_month_spending"]

    # Act
    builder = EvalDBBuilder(db, taxonomy)
    builder.build_from_fixture(fixture)

    # Expected
    expected_count = fixture.ground_truth["transaction_count"]
    expected_total_cents = int(fixture.ground_truth["total_spending"] * 100)

    # Assert - total count
    count_result = db.execute_raw_sql("SELECT COUNT(*) FROM transactions")
    actual_count = count_result.fetchone()[0]  # type: ignore[index]
    assert actual_count == expected_count

    # Assert - total amount
    sum_result = db.execute_raw_sql("SELECT SUM(amount_cents) FROM transactions")
    actual_total_cents = sum_result.fetchone()[0]  # type: ignore[index]
    assert actual_total_cents == expected_total_cents


def test_last_month_spending_food_totals_match_ground_truth() -> None:
    """Test food category totals match ground truth values."""
    # Setup
    db = _create_db()
    taxonomy = _load_full_taxonomy(db)
    fixture = FIXTURES["last_month_spending"]
    builder = EvalDBBuilder(db, taxonomy)
    builder.build_from_fixture(fixture)

    # Expected
    expected_food_total_cents = int(fixture.ground_truth["food_total"] * 100)
    expected_groceries_cents = int(fixture.ground_truth["groceries"] * 100)
    expected_restaurants_cents = int(fixture.ground_truth["restaurants"] * 100)

    # Assert - food total
    food_result = db.execute_raw_sql("""
        SELECT SUM(t.amount_cents)
        FROM transactions t
        JOIN categories c ON t.category_id = c.category_id
        WHERE c.key LIKE 'food_and_dining.%'
    """)
    actual_food_cents = food_result.fetchone()[0]  # type: ignore[index]
    assert actual_food_cents == expected_food_total_cents

    # Assert - groceries
    groceries_result = db.execute_raw_sql("""
        SELECT SUM(t.amount_cents)
        FROM transactions t
        JOIN categories c ON t.category_id = c.category_id
        WHERE c.key = 'food_and_dining.groceries'
    """)
    actual_groceries_cents = groceries_result.fetchone()[0]  # type: ignore[index]
    assert actual_groceries_cents == expected_groceries_cents

    # Assert - restaurants
    restaurants_result = db.execute_raw_sql("""
        SELECT SUM(t.amount_cents)
        FROM transactions t
        JOIN categories c ON t.category_id = c.category_id
        WHERE c.key = 'food_and_dining.restaurants'
    """)
    actual_restaurants_cents = restaurants_result.fetchone()[0]  # type: ignore[index]
    assert actual_restaurants_cents == expected_restaurants_cents


def test_last_month_spending_transportation_total_matches() -> None:
    """Test transportation total matches ground truth."""
    # Setup
    db = _create_db()
    taxonomy = _load_full_taxonomy(db)
    fixture = FIXTURES["last_month_spending"]
    builder = EvalDBBuilder(db, taxonomy)
    builder.build_from_fixture(fixture)

    # Expected
    expected_cents = int(fixture.ground_truth["transportation_total"] * 100)

    # Assert
    result = db.execute_raw_sql("""
        SELECT SUM(t.amount_cents)
        FROM transactions t
        JOIN categories c ON t.category_id = c.category_id
        WHERE c.key LIKE 'transportation_and_auto.%'
    """)
    actual_cents = result.fetchone()[0]  # type: ignore[index]
    assert actual_cents == expected_cents


def test_last_month_spending_date_range_totals_match() -> None:
    """Test first half of month totals match ground truth."""
    # Setup
    db = _create_db()
    taxonomy = _load_full_taxonomy(db)
    fixture = FIXTURES["last_month_spending"]
    builder = EvalDBBuilder(db, taxonomy)
    builder.build_from_fixture(fixture)

    # Expected
    expected_count = fixture.ground_truth["first_half_count"]
    expected_cents = int(fixture.ground_truth["first_half_spending"] * 100)

    # Assert - count
    count_result = db.execute_raw_sql("""
        SELECT COUNT(*)
        FROM transactions
        WHERE posted_at >= '2024-11-01' AND posted_at <= '2024-11-15'
    """)
    actual_count = count_result.fetchone()[0]  # type: ignore[index]
    assert actual_count == expected_count

    # Assert - total
    sum_result = db.execute_raw_sql("""
        SELECT SUM(amount_cents)
        FROM transactions
        WHERE posted_at >= '2024-11-01' AND posted_at <= '2024-11-15'
    """)
    actual_cents = sum_result.fetchone()[0]  # type: ignore[index]
    assert actual_cents == expected_cents


def test_last_month_spending_top_merchants_match() -> None:
    """Test top 3 merchants by spending match ground truth."""
    # Setup
    db = _create_db()
    taxonomy = _load_full_taxonomy(db)
    fixture = FIXTURES["last_month_spending"]
    builder = EvalDBBuilder(db, taxonomy)
    builder.build_from_fixture(fixture)

    # Expected
    expected_top_3 = [
        (
            fixture.ground_truth["top_merchant_1"],
            int(fixture.ground_truth["top_merchant_1_amount"] * 100),
            fixture.ground_truth["top_merchant_1_count"],
        ),
        (
            fixture.ground_truth["top_merchant_2"],
            int(fixture.ground_truth["top_merchant_2_amount"] * 100),
            fixture.ground_truth["top_merchant_2_count"],
        ),
        (
            fixture.ground_truth["top_merchant_3"],
            int(fixture.ground_truth["top_merchant_3_amount"] * 100),
            fixture.ground_truth["top_merchant_3_count"],
        ),
    ]

    # Assert
    result = db.execute_raw_sql("""
        SELECT
            m.display_name,
            SUM(t.amount_cents) as total,
            COUNT(*) as txn_count
        FROM transactions t
        JOIN merchants m ON t.merchant_id = m.merchant_id
        GROUP BY m.merchant_id, m.display_name
        ORDER BY total DESC
        LIMIT 3
    """)

    actual_top_3 = []
    for row in result:
        actual_top_3.append((row[0], row[1], row[2]))  # type: ignore[index]

    assert actual_top_3 == expected_top_3
