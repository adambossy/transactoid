from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from transactoid.tools.categorize.categorizer_tool import CategorizedTransaction

from sqlalchemy import (
    case,
    create_engine,
    text,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import (
    Session,
    sessionmaker,
)

from transactoid.adapters.db.models import (
    Base,
    Category,
    CategoryRow,
    Merchant,
    PlaidItem,
    SaveOutcome,
    SaveRowOutcome,
    Tag,
    Transaction,
    TransactionTag,
    normalize_merchant_name,
)

M = TypeVar("M")


class DB:
    """Database service layer providing ORM models and helper methods."""

    def __init__(self, url: str) -> None:
        """Initialize database connection.

        Args:
            url: Database URL (e.g., "sqlite:///transactoid.db")
        """
        self._url = url
        self._engine = create_engine(url, echo=False)
        self._session_factory = sessionmaker(bind=self._engine, class_=Session)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Context manager for database sessions."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def execute_raw_sql(self, query: str) -> CursorResult[Any]:
        """Execute raw SQL query and return cursor result.

        Returns CursorResult instead of generic Result to access:
        - returns_rows: Whether query returns rows
        - rowcount: Number of rows affected

        Args:
            query: Raw SQL query string

        Returns:
            CursorResult with proper typing for attribute access
        """
        with self.session() as session:  # type: Session
            return cast(CursorResult[Any], session.execute(text(query)))

    def run_sql(
        self,
        sql: str,
        *,
        model: type[M],
        pk_column: str,
    ) -> list[M]:
        """Execute raw SQL and return ORM model instances.

        Args:
            sql: Raw SQL SELECT query
            model: SQLAlchemy model class to return
            pk_column: Name of primary key column in SQL result

        Returns:
            List of ORM model instances in the order returned by SQL
        """
        with self.session() as session:  # type: Session
            result = session.execute(text(sql))
            rows = result.fetchall()

            if not rows:
                return []

            # Get column index for primary key
            keys = list(result.keys())
            pk_index = keys.index(pk_column)

            # Extract primary key values
            pk_values = [row[pk_index] for row in rows]

            # Query ORM models by primary keys
            pk_attr = getattr(model, pk_column)
            orm_instances = session.query(model).filter(pk_attr.in_(pk_values)).all()

            # Expunge all instances before returning
            for instance in orm_instances:
                session.expunge(instance)

            # Create mapping for quick lookup
            instance_map = {getattr(inst, pk_column): inst for inst in orm_instances}

            # Return in SQL result order
            return [
                instance_map[pk_val] for pk_val in pk_values if pk_val in instance_map
            ]

    def fetch_transactions_by_ids_preserving_order(
        self,
        ids: list[int],
    ) -> list[Transaction]:
        """Fetch transactions by IDs preserving input order.

        Args:
            ids: List of transaction IDs

        Returns:
            List of Transaction instances in the same order as input IDs
        """
        if not ids:
            return []

        with self.session() as session:  # type: Session
            # Use CASE WHEN to preserve order
            order_case = case(
                {id_val: idx for idx, id_val in enumerate(ids)},
                value=Transaction.transaction_id,
            )
            transactions = (
                session.query(Transaction)
                .filter(Transaction.transaction_id.in_(ids))
                .order_by(order_case)
                .all()
            )

            # Expunge all transactions before returning
            for txn in transactions:
                session.expunge(txn)
            # Create mapping and return in input order
            txn_map = {txn.transaction_id: txn for txn in transactions}
            return [txn_map[tid] for tid in ids if tid in txn_map]

    def get_category_id_by_key(self, key: str) -> int | None:
        """Get category ID by key.

        Args:
            key: Category key

        Returns:
            Category ID or None if not found
        """
        with self.session() as session:  # type: Session
            category = session.query(Category).filter(Category.key == key).first()
            return category.category_id if category else None

    def find_merchant_by_normalized_name(self, normalized_name: str) -> Merchant | None:
        """Find merchant by normalized name.

        Args:
            normalized_name: Normalized merchant name

        Returns:
            Merchant instance or None if not found
        """
        with self.session() as session:  # type: Session
            merchant = (
                session.query(Merchant)
                .filter(Merchant.normalized_name == normalized_name)
                .first()
            )
            if merchant:
                session.expunge(merchant)
            return merchant

    def create_merchant(
        self,
        *,
        normalized_name: str,
        display_name: str | None,
    ) -> Merchant:
        """Create a new merchant.

        Args:
            normalized_name: Normalized merchant name (must be unique)
            display_name: Display name for merchant

        Returns:
            Created Merchant instance
        """
        with self.session() as session:  # type: Session
            merchant = Merchant(
                normalized_name=normalized_name, display_name=display_name
            )
            session.add(merchant)
            session.flush()
            session.refresh(merchant)
            session.expunge(merchant)
            return merchant

    def get_transaction_by_external(
        self,
        *,
        external_id: str,
        source: str,
    ) -> Transaction | None:
        """Get transaction by external ID and source.

        Args:
            external_id: External transaction ID
            source: Source identifier (e.g., "PLAID", "CSV")

        Returns:
            Transaction instance or None if not found
        """
        with self.session() as session:  # type: Session
            transaction = (
                session.query(Transaction)
                .filter(
                    Transaction.external_id == external_id, Transaction.source == source
                )
                .first()
            )
            if transaction:
                session.expunge(transaction)
            return transaction

    def insert_transaction(self, data: dict[str, Any]) -> Transaction:
        """Insert a new transaction.

        Args:
            data: Transaction data dictionary with fields:
                - external_id, source, account_id, posted_at, amount_cents, currency
                - merchant_descriptor (optional), merchant_id (optional)
                - category_id (optional), institution (optional)

        Returns:
            Created Transaction instance
        """
        with self.session() as session:  # type: Session
            # Resolve merchant if merchant_descriptor is provided
            merchant_id = data.get("merchant_id")
            if (
                merchant_id is None
                and "merchant_descriptor" in data
                and data["merchant_descriptor"]
            ):
                normalized_name = normalize_merchant_name(data["merchant_descriptor"])
                merchant = (
                    session.query(Merchant)
                    .filter(Merchant.normalized_name == normalized_name)
                    .first()
                )
                if merchant is None:
                    merchant = Merchant(
                        normalized_name=normalized_name,
                        display_name=data["merchant_descriptor"],
                    )
                    session.add(merchant)
                    session.flush()
                merchant_id = merchant.merchant_id

            transaction = Transaction(
                external_id=data["external_id"],
                source=data["source"],
                account_id=data["account_id"],
                posted_at=data["posted_at"],
                amount_cents=data["amount_cents"],
                currency=data["currency"],
                merchant_descriptor=data.get("merchant_descriptor"),
                merchant_id=merchant_id,
                category_id=data.get("category_id"),
                institution=data.get("institution"),
                is_verified=data.get("is_verified", False),
            )
            session.add(transaction)
            session.flush()
            session.refresh(transaction)
            session.expunge(transaction)
            return transaction

    def update_transaction_mutable(
        self,
        transaction_id: int,
        data: dict[str, Any],
    ) -> Transaction:
        """Update mutable fields of a transaction.

        Only updates if transaction is not verified (is_verified=False).

        Args:
            transaction_id: Transaction ID to update
            data: Dictionary of fields to update

        Returns:
            Updated Transaction instance

        Raises:
            ValueError: If transaction is verified and cannot be updated
        """
        with self.session() as session:  # type: Session
            transaction = (
                session.query(Transaction)
                .filter(Transaction.transaction_id == transaction_id)
                .first()
            )
            if transaction is None:
                raise ValueError(f"Transaction {transaction_id} not found")

            if transaction.is_verified:
                raise ValueError(
                    f"Transaction {transaction_id} is verified and cannot be updated"
                )

            # Resolve merchant if merchant_descriptor is provided
            if "merchant_descriptor" in data and data["merchant_descriptor"]:
                normalized_name = normalize_merchant_name(data["merchant_descriptor"])
                merchant = (
                    session.query(Merchant)
                    .filter(Merchant.normalized_name == normalized_name)
                    .first()
                )
                if merchant is None:
                    merchant = Merchant(
                        normalized_name=normalized_name,
                        display_name=data["merchant_descriptor"],
                    )
                    session.add(merchant)
                    session.flush()
                data["merchant_id"] = merchant.merchant_id

            # Update mutable fields
            for key, value in data.items():
                if key in (
                    "category_id",
                    "merchant_id",
                    "amount_cents",
                    "merchant_descriptor",
                ):
                    setattr(transaction, key, value)

            session.flush()
            session.refresh(transaction)
            session.expunge(transaction)
            return transaction

    def recategorize_unverified_by_merchant(
        self,
        merchant_id: int,
        category_id: int,
    ) -> int:
        """Recategorize all unverified transactions for a merchant.

        Args:
            merchant_id: Merchant ID
            category_id: New category ID

        Returns:
            Number of transactions updated
        """
        with self.session() as session:  # type: Session
            result = (
                session.query(Transaction)
                .filter(
                    Transaction.merchant_id == merchant_id,
                    ~Transaction.is_verified,
                )
                .update({"category_id": category_id}, synchronize_session=False)
            )
            return result

    def upsert_tag(self, name: str, description: str | None = None) -> Tag:
        """Insert or update a tag.

        Args:
            name: Tag name (unique)
            description: Tag description

        Returns:
            Tag instance
        """
        with self.session() as session:  # type: Session
            tag = session.query(Tag).filter(Tag.name == name).first()
            if tag is None:
                tag = Tag(name=name, description=description)
                session.add(tag)
            else:
                if description is not None:
                    tag.description = description
            session.flush()
            session.refresh(tag)
            session.expunge(tag)
            return tag

    def attach_tags(self, transaction_ids: list[int], tag_ids: list[int]) -> int:
        """Attach tags to transactions (bulk insert, skip duplicates).

        Args:
            transaction_ids: List of transaction IDs
            tag_ids: List of tag IDs

        Returns:
            Number of tag attachments created
        """
        if not transaction_ids or not tag_ids:
            return 0

        with self.session() as session:  # type: Session
            # Check existing relationships
            existing = (
                session.query(TransactionTag)
                .filter(
                    TransactionTag.transaction_id.in_(transaction_ids),
                    TransactionTag.tag_id.in_(tag_ids),
                )
                .all()
            )
            existing_set = {(rel.transaction_id, rel.tag_id) for rel in existing}

            # Insert new relationships
            new_count = 0
            for transaction_id in transaction_ids:
                for tag_id in tag_ids:
                    if (transaction_id, tag_id) not in existing_set:
                        rel = TransactionTag(
                            transaction_id=transaction_id, tag_id=tag_id
                        )
                        session.add(rel)
                        new_count += 1

            return new_count

    def delete_transactions_by_external_ids(
        self,
        external_ids: list[str],
        source: str = "PLAID",
    ) -> int:
        """Delete transactions by their external IDs.

        Only deletes unverified transactions to respect immutability guarantees.

        Args:
            external_ids: List of external transaction IDs (e.g., Plaid transaction_id)
            source: Source identifier (default: "PLAID")

        Returns:
            Number of transactions deleted
        """
        if not external_ids:
            return 0

        with self.session() as session:  # type: Session
            result = (
                session.query(Transaction)
                .filter(
                    Transaction.external_id.in_(external_ids),
                    Transaction.source == source,
                    ~Transaction.is_verified,
                )
                .delete(synchronize_session=False)
            )
            return result

    def save_transactions(
        self,
        category_lookup: Callable[[str], int | None],
        txns: Iterable[CategorizedTransaction],
    ) -> SaveOutcome:
        """Save categorized transactions to the database.

        Args:
            category_lookup: Function that takes a category key and returns category ID
            txns: Iterable of categorized transactions to save

        Returns:
            SaveOutcome with details about the save operation
        """
        inserted_count = 0
        updated_count = 0
        skipped_verified_count = 0
        skipped_duplicate_count = 0
        rows: list[SaveRowOutcome] = []

        for cat_txn in txns:
            txn = cat_txn.txn

            # Determine category key (prefer revised if present)
            category_key = (
                cat_txn.revised_category_key
                if cat_txn.revised_category_key
                else cat_txn.category_key
            )
            category_id = category_lookup(category_key) if category_key else None

            # Extract transaction data
            # Map from Transaction TypedDict to database fields
            merchant_descriptor = txn.get("merchant_name") or txn.get("name")
            external_id = txn.get("transaction_id") or ""
            source = "PLAID"  # Default, should come from ingest tool context

            # Parse date
            posted_at_str = txn.get("date", "")
            try:
                posted_at = datetime.strptime(posted_at_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                rows.append(
                    SaveRowOutcome(
                        external_id=external_id,
                        source=source,
                        action="skipped-duplicate",
                        reason=f"Invalid date: {posted_at_str}",
                    )
                )
                skipped_duplicate_count += 1
                continue

            # Convert amount to cents
            amount = txn.get("amount", 0.0)
            amount_cents = int(amount * 100)

            # Currency
            currency = txn.get("iso_currency_code") or "USD"

            # Check if transaction exists
            existing = self.get_transaction_by_external(
                external_id=external_id, source=source
            )

            if existing:
                is_verified = existing.is_verified
                existing_id = existing.transaction_id
                if is_verified:
                    rows.append(
                        SaveRowOutcome(
                            external_id=external_id,
                            source=source,
                            action="skipped-verified",
                            transaction_id=existing_id,
                            reason="Transaction is verified and cannot be updated",
                        )
                    )
                    skipped_verified_count += 1
                    continue

                # Update existing unverified transaction
                update_data: dict[str, Any] = {
                    "category_id": category_id,
                    "merchant_descriptor": merchant_descriptor,
                    "amount_cents": amount_cents,
                }
                try:
                    updated_txn = self.update_transaction_mutable(
                        existing_id, update_data
                    )
                    rows.append(
                        SaveRowOutcome(
                            external_id=external_id,
                            source=source,
                            action="updated",
                            transaction_id=updated_txn.transaction_id,
                        )
                    )
                    updated_count += 1
                except ValueError as e:
                    rows.append(
                        SaveRowOutcome(
                            external_id=external_id,
                            source=source,
                            action="skipped-verified",
                            transaction_id=existing_id,
                            reason=str(e),
                        )
                    )
                    skipped_verified_count += 1
            else:
                # Insert new transaction
                insert_data: dict[str, Any] = {
                    "external_id": external_id,
                    "source": source,
                    "account_id": txn.get("account_id", ""),
                    "posted_at": posted_at,
                    "amount_cents": amount_cents,
                    "currency": currency,
                    "merchant_descriptor": merchant_descriptor,
                    "category_id": category_id,
                    "institution": None,  # Should come from ingest tool context
                }
                new_txn = self.insert_transaction(insert_data)
                rows.append(
                    SaveRowOutcome(
                        external_id=external_id,
                        source=source,
                        action="inserted",
                        transaction_id=new_txn.transaction_id,
                    )
                )
                inserted_count += 1

        return SaveOutcome(
            inserted=inserted_count,
            updated=updated_count,
            skipped_verified=skipped_verified_count,
            skipped_duplicate=skipped_duplicate_count,
            rows=rows,
        )

    def compact_schema_hint(self) -> dict[str, Any]:
        """Return compact schema metadata for LLM prompts.

        Returns:
            Dictionary with table names, column names, types, and relationships
        """
        return {
            "tables": {
                "merchants": {
                    "columns": {
                        "merchant_id": "INTEGER PRIMARY KEY",
                        "normalized_name": "TEXT UNIQUE",
                        "display_name": "TEXT",
                        "created_at": "TIMESTAMP",
                        "updated_at": "TIMESTAMP",
                    },
                    "relationships": ["transactions"],
                },
                "categories": {
                    "columns": {
                        "category_id": "INTEGER PRIMARY KEY",
                        "parent_id": "INTEGER FOREIGN KEY",
                        "key": "TEXT UNIQUE",
                        "name": "TEXT",
                        "description": "TEXT",
                        "rules": "TEXT",
                        "created_at": "TIMESTAMP",
                        "updated_at": "TIMESTAMP",
                    },
                    "relationships": ["parent", "children", "transactions"],
                },
                "transactions": {
                    "columns": {
                        "transaction_id": "INTEGER PRIMARY KEY",
                        "external_id": "TEXT",
                        "source": "TEXT",
                        "account_id": "TEXT",
                        "posted_at": "DATE",
                        "amount_cents": "INTEGER",
                        "currency": "TEXT",
                        "merchant_descriptor": "TEXT",
                        "merchant_id": "INTEGER FOREIGN KEY",
                        "category_id": "INTEGER FOREIGN KEY",
                        "institution": "TEXT",
                        "is_verified": "BOOLEAN",
                        "created_at": "TIMESTAMP",
                        "updated_at": "TIMESTAMP",
                    },
                    "relationships": ["merchant", "category", "tags"],
                    "constraints": ["UNIQUE(external_id, source)"],
                },
                "tags": {
                    "columns": {
                        "tag_id": "INTEGER PRIMARY KEY",
                        "name": "TEXT UNIQUE",
                        "description": "TEXT",
                        "created_at": "TIMESTAMP",
                        "updated_at": "TIMESTAMP",
                    },
                    "relationships": ["transactions"],
                },
                "transaction_tags": {
                    "columns": {
                        "transaction_id": "INTEGER PRIMARY KEY",
                        "tag_id": "INTEGER PRIMARY KEY",
                    },
                    "relationships": ["transaction", "tag"],
                },
            },
        }

    def fetch_categories(self) -> list[CategoryRow]:
        """Fetch all categories as CategoryRow TypedDicts.

        Returns:
            List of CategoryRow dictionaries
        """
        with self.session() as session:  # type: Session
            categories = session.query(Category).all()

            # Build parent_key lookup
            id_to_key: dict[int, str] = {cat.category_id: cat.key for cat in categories}

            rows: list[CategoryRow] = []
            for cat in categories:
                parent_key = None
                if cat.parent_id is not None:
                    parent_key = id_to_key.get(cat.parent_id)

                rows.append(
                    CategoryRow(
                        category_id=cat.category_id,
                        parent_id=cat.parent_id,
                        key=cat.key,
                        name=cat.name,
                        description=cat.description,
                        parent_key=parent_key,
                    )
                )

            return rows

    def replace_categories_rows(self, rows: Sequence[CategoryRow]) -> None:
        """Replace categories with pre-built rows (ids and parent ids already resolved).

        Args:
            rows: Sequence of CategoryRow dictionaries with resolved IDs
        """
        with self.session() as session:  # type: Session
            # Delete all existing categories
            session.query(Category).delete()

            # Insert new categories
            for row in rows:
                category = Category(
                    category_id=row["category_id"],
                    parent_id=row["parent_id"],
                    key=row["key"],
                    name=row["name"],
                    description=row.get("description"),
                    rules=None,  # Rules not in CategoryRow, set to None
                )
                session.add(category)

            session.flush()

    def save_plaid_item(
        self,
        *,
        item_id: str,
        access_token: str,
        institution_id: str | None = None,
        institution_name: str | None = None,
    ) -> PlaidItem:
        """Save or update a Plaid item.

        Args:
            item_id: Plaid item ID (primary key)
            access_token: Plaid access token
            institution_id: Optional institution ID
            institution_name: Optional institution name

        Returns:
            Created or updated PlaidItem instance
        """
        with self.session() as session:  # type: Session
            item = session.query(PlaidItem).filter_by(item_id=item_id).first()
            if item is None:
                item = PlaidItem(
                    item_id=item_id,
                    access_token=access_token,
                    institution_id=institution_id,
                    institution_name=institution_name,
                )
                session.add(item)
            else:
                item.access_token = access_token
                item.institution_id = institution_id
                item.institution_name = institution_name
                item.updated_at = datetime.now()
            session.flush()
            session.refresh(item)
            session.expunge(item)
            return item

    def get_plaid_item(self, item_id: str) -> PlaidItem | None:
        """Retrieve a Plaid item by item_id.

        Args:
            item_id: Plaid item ID

        Returns:
            PlaidItem instance or None if not found
        """
        with self.session() as session:  # type: Session
            item = session.query(PlaidItem).filter_by(item_id=item_id).first()
            if item:
                session.expunge(item)
            return item

    def insert_plaid_item(
        self,
        item_id: str,
        access_token: str,
        institution_id: str | None = None,
        institution_name: str | None = None,
    ) -> PlaidItem:
        """Insert a new Plaid item.

        Args:
            item_id: Unique identifier for the Plaid item
            access_token: Access token for the Plaid item
            institution_id: Optional Plaid institution ID
            institution_name: Optional name of the institution

        Returns:
            Created PlaidItem instance
        """
        with self.session() as session:  # type: Session
            plaid_item = PlaidItem(
                item_id=item_id,
                access_token=access_token,
                institution_id=institution_id,
                institution_name=institution_name,
            )
            session.add(plaid_item)
            session.flush()
            session.refresh(plaid_item)
            session.expunge(plaid_item)
            return plaid_item

    def list_plaid_items(self) -> list[PlaidItem]:
        """List all Plaid items.

        Returns:
            List of all PlaidItem instances
        """
        with self.session() as session:  # type: Session
            items = session.query(PlaidItem).all()
            for item in items:
                session.expunge(item)
            return items
