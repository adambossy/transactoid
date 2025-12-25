from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class TransactionFixture:
    """Synthetic transaction dataset for evaluation."""

    name: str
    transactions: list[dict[str, Any]]
    ground_truth: dict[str, Any]
    description: str


# Helper to create transaction dict
def _txn(
    external_id: str,
    amount_cents: int,
    posted_at: date,
    merchant_descriptor: str,
    category_key: str,
) -> dict[str, Any]:
    """Create transaction dict for fixture."""
    return {
        "external_id": external_id,
        "amount_cents": amount_cents,
        "posted_at": posted_at,
        "merchant_descriptor": merchant_descriptor,
        "category_key": category_key,
    }


# Registry of all fixtures
FIXTURES: dict[str, TransactionFixture] = {
    "last_month_spending": TransactionFixture(
        name="last_month_spending",
        transactions=[
            # First half (Nov 1-15): 20 transactions totaling $1,150.00
            # Whole Foods - groceries (4 transactions, $245.00 total)
            _txn("txn_001", 6500, date(2024, 11, 2), "Whole Foods Market", "food_and_dining.groceries"),
            _txn("txn_002", 7200, date(2024, 11, 5), "Whole Foods Market", "food_and_dining.groceries"),
            _txn("txn_003", 5800, date(2024, 11, 9), "Whole Foods Market", "food_and_dining.groceries"),
            _txn("txn_004", 5000, date(2024, 11, 13), "Whole Foods Market", "food_and_dining.groceries"),
            # Other groceries ($275.00)
            _txn("txn_005", 8500, date(2024, 11, 1), "Trader Joes", "food_and_dining.groceries"),
            _txn("txn_006", 6200, date(2024, 11, 4), "Safeway", "food_and_dining.groceries"),
            _txn("txn_007", 5800, date(2024, 11, 7), "Trader Joes", "food_and_dining.groceries"),
            _txn("txn_008", 7000, date(2024, 11, 11), "Safeway", "food_and_dining.groceries"),
            # Restaurants ($205.00)
            _txn("txn_009", 12550, date(2024, 11, 3), "Chipotle Mexican Grill", "food_and_dining.restaurants"),
            _txn("txn_010", 3200, date(2024, 11, 6), "Starbucks", "food_and_dining.restaurants"),
            _txn("txn_011", 4500, date(2024, 11, 10), "Panera Bread", "food_and_dining.restaurants"),
            _txn("txn_012", 300, date(2024, 11, 14), "Starbucks", "food_and_dining.restaurants"),
            # Shell gas (3 transactions first half, $90.00)
            _txn("txn_013", 3500, date(2024, 11, 2), "Shell", "transportation_and_auto.fuel"),
            _txn("txn_014", 2800, date(2024, 11, 8), "Shell", "transportation_and_auto.fuel"),
            _txn("txn_015", 2700, date(2024, 11, 14), "Shell", "transportation_and_auto.fuel"),
            # Target (2 transactions first half, $110.00)
            _txn("txn_016", 6500, date(2024, 11, 5), "Target", "shopping_and_personal_care.household_supplies"),
            _txn("txn_017", 4500, date(2024, 11, 12), "Target", "shopping_and_personal_care.household_supplies"),
            # Other first half ($224.50)
            _txn("txn_018", 7500, date(2024, 11, 1), "AT&T", "housing_and_utilities.mobile_phone"),
            _txn("txn_019", 6000, date(2024, 11, 3), "PG&E", "housing_and_utilities.electricity"),
            _txn("txn_020", 8950, date(2024, 11, 15), "Netflix", "entertainment_and_subscriptions.streaming_video"),
            # Second half (Nov 16-30): 22 transactions totaling $1,300.50
            # Shell gas (3 more transactions, $90.00 more = $180.00 total)
            _txn("txn_021", 3200, date(2024, 11, 18), "Shell", "transportation_and_auto.fuel"),
            _txn("txn_022", 2900, date(2024, 11, 23), "Shell", "transportation_and_auto.fuel"),
            _txn("txn_023", 2900, date(2024, 11, 28), "Shell", "transportation_and_auto.fuel"),
            # Uber/Lyft - transportation ($245.00 more = $425.00 total transportation)
            _txn("txn_024", 2800, date(2024, 11, 16), "Uber", "transportation_and_auto.rides_and_taxis"),
            _txn("txn_025", 3200, date(2024, 11, 17), "Lyft", "transportation_and_auto.rides_and_taxis"),
            _txn("txn_026", 1500, date(2024, 11, 19), "Uber", "transportation_and_auto.rides_and_taxis"),
            _txn("txn_027", 3400, date(2024, 11, 22), "Lyft", "transportation_and_auto.rides_and_taxis"),
            _txn("txn_028", 2100, date(2024, 11, 25), "Uber", "transportation_and_auto.rides_and_taxis"),
            _txn("txn_029", 1500, date(2024, 11, 27), "Lyft", "transportation_and_auto.rides_and_taxis"),
            _txn("txn_030", 10000, date(2024, 11, 20), "Bay Area Transit", "transportation_and_auto.public_transit"),
            # Target (1 more transaction, $55.00 = $165.00 total)
            _txn("txn_031", 5500, date(2024, 11, 21), "Target", "shopping_and_personal_care.household_supplies"),
            # Restaurants ($125.00 more = $330.00 total)
            _txn("txn_032", 5400, date(2024, 11, 16), "Olive Garden", "food_and_dining.restaurants"),
            _txn("txn_033", 3200, date(2024, 11, 20), "Starbucks", "food_and_dining.restaurants"),
            _txn("txn_034", 1750, date(2024, 11, 24), "Dunkin Donuts", "food_and_dining.restaurants"),
            _txn("txn_035", 2100, date(2024, 11, 26), "Starbucks", "food_and_dining.restaurants"),
            # Shopping and other ($845.00)
            _txn("txn_036", 7000, date(2024, 11, 17), "Amazon", "shopping_and_personal_care.electronics_and_gadgets"),
            _txn("txn_037", 7000, date(2024, 11, 19), "Amazon", "shopping_and_personal_care.household_supplies"),
            _txn("txn_038", 16000, date(2024, 11, 22), "CVS Pharmacy", "health_and_wellness.pharmacy_and_prescriptions"),
            _txn("txn_039", 14000, date(2024, 11, 24), "Costco", "shopping_and_personal_care.household_supplies"),
            _txn("txn_040", 15000, date(2024, 11, 25), "Spotify", "entertainment_and_subscriptions.music_and_audio"),
            _txn("txn_041", 14550, date(2024, 11, 28), "Steam", "entertainment_and_subscriptions.gaming"),
            _txn("txn_042", 5050, date(2024, 11, 30), "AMC Theatres", "entertainment_and_subscriptions.hobbies_and_leisure"),
        ],
        ground_truth={
            # Overall
            "total_spending": 2450.50,
            "transaction_count": 42,
            # Food breakdown
            "food_total": 850.00,
            "groceries": 520.00,
            "restaurants": 330.00,
            "groceries_pct": 61.2,
            "restaurants_pct": 38.8,
            "top_restaurant": "Chipotle",
            "top_restaurant_amount": 125.50,
            # Transportation
            "transportation_total": 425.00,
            # Date range
            "first_half_spending": 1150.00,
            "first_half_count": 20,
            # Top merchants
            "top_merchant_1": "Whole Foods Market",
            "top_merchant_1_amount": 245.00,
            "top_merchant_1_count": 4,
            "top_merchant_2": "Shell",
            "top_merchant_2_amount": 180.00,
            "top_merchant_2_count": 6,
            "top_merchant_3": "Target",
            "top_merchant_3_amount": 165.00,
            "top_merchant_3_count": 3,
        },
        description="42 transactions across November 2024 with known totals for comprehensive testing",
    ),
}
