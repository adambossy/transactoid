from __future__ import annotations

from evals.data.fixtures import TransactionFixture
from services.db import DB
from services.taxonomy import Taxonomy


class EvalDBBuilder:
    """Builds test databases from transaction fixtures."""

    def __init__(self, db: DB, taxonomy: Taxonomy) -> None:
        """Initialize builder with database and taxonomy.

        Args:
            db: Database instance to populate
            taxonomy: Taxonomy instance for category validation
        """
        self._db = db
        self._taxonomy = taxonomy

    def build_from_fixture(self, fixture: TransactionFixture) -> None:
        """Populate database with fixture data.

        Args:
            fixture: TransactionFixture containing transactions and ground truth

        Raises:
            ValueError: If a category_key in fixture is not valid in taxonomy
        """
        # Insert Plaid items first (if present)
        if fixture.plaid_items:
            for plaid_item_data in fixture.plaid_items:
                self._db.insert_plaid_item(
                    item_id=plaid_item_data["item_id"],
                    access_token=plaid_item_data["access_token"],
                    institution_id=plaid_item_data.get("institution_id"),
                    institution_name=plaid_item_data.get("institution_name"),
                )

        # Insert transactions
        for txn_data in fixture.transactions:
            # Validate category key exists
            category_key = txn_data["category_key"]
            if not self._taxonomy.is_valid_key(category_key):
                msg = f"Invalid category key '{category_key}' in fixture"
                raise ValueError(msg)

            # Get category ID from taxonomy
            category_id = self._db.get_category_id_by_key(category_key)
            if category_id is None:
                msg = f"Category key '{category_key}' not found in database"
                raise ValueError(msg)

            # Insert transaction
            self._db.insert_transaction(
                {
                    "external_id": txn_data["external_id"],
                    "source": "EVAL",
                    "account_id": "test_account",
                    "posted_at": txn_data["posted_at"],
                    "amount_cents": txn_data["amount_cents"],
                    "currency": "USD",
                    "merchant_descriptor": txn_data["merchant_descriptor"],
                    "category_id": category_id,
                    "is_verified": False,
                }
            )
