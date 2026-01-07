from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from transactoid.tools.categorize.categorizer_tool import CategorizedTransaction

from sqlalchemy import (
    case,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from transactoid.adapters.db.models import (
    Base,
    Category,
    CategoryRow,
    DerivedTransaction,
    Merchant,
    PlaidItem,
    PlaidTransaction,
    SaveOutcome,
    SaveRowOutcome,
    Tag,
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
        self._engine = create_engine(url, echo=False)
        self._session_factory = sessionmaker(bind=self._engine, class_=Session)

    def create_schema(self) -> None:
        """Create database tables if they do not already exist."""
        Base.metadata.create_all(self._engine)

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
    ) -> list[DerivedTransaction]:
        """Fetch derived transactions by IDs preserving input order.

        Args:
            ids: List of transaction IDs

        Returns:
            List of DerivedTransaction instances in the same order as input IDs
        """
        if not ids:
            return []

        with self.session() as session:  # type: Session
            # Use CASE WHEN to preserve order
            order_case = case(
                {id_val: idx for idx, id_val in enumerate(ids)},
                value=DerivedTransaction.transaction_id,
            )
            transactions = (
                session.query(DerivedTransaction)
                .filter(DerivedTransaction.transaction_id.in_(ids))
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
        source: str = "PLAID",
    ) -> DerivedTransaction | None:
        """Get derived transaction by external ID.

        Args:
            external_id: External transaction ID
            source: Ignored (kept for backward compatibility)

        Returns:
            DerivedTransaction instance or None if not found
        """
        with self.session() as session:  # type: Session
            transaction = (
                session.query(DerivedTransaction)
                .filter(DerivedTransaction.external_id == external_id)
                .first()
            )
            if transaction:
                session.expunge(transaction)
            return transaction

    def insert_transaction(self, data: dict[str, Any]) -> DerivedTransaction:
        """Insert a new derived transaction (legacy wrapper).

        DEPRECATED: Use insert_derived_transaction() instead.
        This method creates both a PlaidTransaction and DerivedTransaction
        for backward compatibility.

        Args:
            data: Transaction data dictionary with fields:
                - external_id, source, account_id, posted_at, amount_cents, currency
                - merchant_descriptor (optional), merchant_id (optional)
                - category_id (optional), institution (optional)

        Returns:
            Created DerivedTransaction instance
        """
        # First create PlaidTransaction
        plaid_txn = self.upsert_plaid_transaction(
            external_id=data["external_id"],
            source=data.get("source", "PLAID"),
            account_id=data["account_id"],
            posted_at=data["posted_at"],
            amount_cents=data["amount_cents"],
            currency=data["currency"],
            merchant_descriptor=data.get("merchant_descriptor"),
            institution=data.get("institution"),
        )

        # Then create DerivedTransaction
        derived_data = {
            "plaid_transaction_id": plaid_txn.plaid_transaction_id,
            "external_id": data["external_id"],
            "amount_cents": data["amount_cents"],
            "posted_at": data["posted_at"],
            "merchant_descriptor": data.get("merchant_descriptor"),
            "merchant_id": data.get("merchant_id"),
            "category_id": data.get("category_id"),
            "is_verified": data.get("is_verified", False),
        }
        return self.insert_derived_transaction(derived_data)

    def update_transaction_mutable(
        self,
        transaction_id: int,
        data: dict[str, Any],
    ) -> DerivedTransaction:
        """Update mutable fields of a derived transaction (legacy wrapper).

        DEPRECATED: Use update_derived_mutable() instead.

        Only updates if transaction is not verified (is_verified=False).

        Args:
            transaction_id: Transaction ID to update
            data: Dictionary of fields to update

        Returns:
            Updated DerivedTransaction instance

        Raises:
            ValueError: If transaction is verified and cannot be updated
        """
        return self.update_derived_mutable(transaction_id, data)

    def recategorize_unverified_by_merchant(
        self,
        merchant_id: int,
        category_id: int,
    ) -> int:
        """Recategorize all unverified derived transactions for a merchant.

        Args:
            merchant_id: Merchant ID
            category_id: New category ID

        Returns:
            Number of transactions updated
        """
        with self.session() as session:  # type: Session
            result = (
                session.query(DerivedTransaction)
                .filter(
                    DerivedTransaction.merchant_id == merchant_id,
                    ~DerivedTransaction.is_verified,
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
        """Delete derived transactions by their external IDs (legacy wrapper).

        DEPRECATED: Use delete_plaid_transactions_by_external_ids() for full
        cascade delete, or delete_derived_by_plaid_ids() for derived-only.

        Only deletes unverified transactions to respect immutability guarantees.

        Args:
            external_ids: List of external transaction IDs (e.g., Plaid transaction_id)
            source: Source identifier (default: "PLAID") - ignored

        Returns:
            Number of transactions deleted
        """
        if not external_ids:
            return 0

        with self.session() as session:  # type: Session
            result = (
                session.query(DerivedTransaction)
                .filter(
                    DerivedTransaction.external_id.in_(external_ids),
                    ~DerivedTransaction.is_verified,
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
                    "relationships": ["derived_transactions"],
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
                    "relationships": ["parent", "children", "derived_transactions"],
                },
                "plaid_transactions": {
                    "columns": {
                        "plaid_transaction_id": "INTEGER PRIMARY KEY",
                        "external_id": "TEXT",
                        "source": "TEXT",
                        "account_id": "TEXT",
                        "posted_at": "DATE",
                        "amount_cents": "INTEGER",
                        "currency": "TEXT",
                        "merchant_descriptor": "TEXT",
                        "institution": "TEXT",
                        "created_at": "TIMESTAMP",
                        "updated_at": "TIMESTAMP",
                    },
                    "relationships": ["derived_transactions"],
                    "constraints": ["UNIQUE(external_id, source)"],
                    "notes": (
                        "Immutable source data from Plaid. "
                        "Do NOT query directly for spending analysis."
                    ),
                },
                "derived_transactions": {
                    "columns": {
                        "transaction_id": "INTEGER PRIMARY KEY",
                        "plaid_transaction_id": "INTEGER FOREIGN KEY",
                        "external_id": "TEXT UNIQUE",
                        "amount_cents": "INTEGER",
                        "posted_at": "DATE",
                        "merchant_descriptor": "TEXT",
                        "merchant_id": "INTEGER FOREIGN KEY",
                        "category_id": "INTEGER FOREIGN KEY",
                        "is_verified": "BOOLEAN",
                        "created_at": "TIMESTAMP",
                        "updated_at": "TIMESTAMP",
                    },
                    "relationships": [
                        "plaid_transaction",
                        "merchant",
                        "category",
                        "tags",
                    ],
                    "notes": (
                        "Primary table for all spending queries and analysis. "
                        "May have multiple rows per Plaid transaction "
                        "(Amazon item splits)."
                    ),
                },
                "tags": {
                    "columns": {
                        "tag_id": "INTEGER PRIMARY KEY",
                        "name": "TEXT UNIQUE",
                        "description": "TEXT",
                        "created_at": "TIMESTAMP",
                        "updated_at": "TIMESTAMP",
                    },
                    "relationships": ["derived_transactions"],
                },
                "transaction_tags": {
                    "columns": {
                        "transaction_id": "INTEGER PRIMARY KEY FOREIGN KEY",
                        "tag_id": "INTEGER PRIMARY KEY FOREIGN KEY",
                    },
                    "relationships": ["derived_transaction", "tag"],
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

    def get_sync_cursor(self, item_id: str) -> str | None:
        """Get the sync cursor for a Plaid item.

        Args:
            item_id: Plaid item ID

        Returns:
            Sync cursor string or None if not set
        """
        with self.session() as session:  # type: Session
            item = session.query(PlaidItem).filter_by(item_id=item_id).first()
            return item.sync_cursor if item else None

    def set_sync_cursor(self, item_id: str, cursor: str) -> None:
        """Set the sync cursor for a Plaid item.

        Args:
            item_id: Plaid item ID
            cursor: Sync cursor string from Plaid
        """
        with self.session() as session:  # type: Session
            item = session.query(PlaidItem).filter_by(item_id=item_id).first()
            if item:
                item.sync_cursor = cursor
                item.updated_at = datetime.now()

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

    # Plaid Transactions methods

    def upsert_plaid_transaction(
        self,
        external_id: str,
        source: str,
        account_id: str,
        posted_at: date,
        amount_cents: int,
        currency: str,
        merchant_descriptor: str | None,
        institution: str | None,
    ) -> PlaidTransaction:
        """Insert or update a Plaid transaction.

        Args:
            external_id: External transaction ID (e.g., Plaid transaction_id)
            source: Source identifier ("PLAID" or "CSV")
            account_id: Account ID
            posted_at: Posted date
            amount_cents: Amount in cents
            currency: Currency code
            merchant_descriptor: Merchant descriptor
            institution: Institution name

        Returns:
            Created or updated PlaidTransaction instance
        """
        with self.session() as session:  # type: Session
            plaid_txn = (
                session.query(PlaidTransaction)
                .filter(
                    PlaidTransaction.external_id == external_id,
                    PlaidTransaction.source == source,
                )
                .first()
            )

            if plaid_txn is None:
                plaid_txn = PlaidTransaction(
                    external_id=external_id,
                    source=source,
                    account_id=account_id,
                    posted_at=posted_at,
                    amount_cents=amount_cents,
                    currency=currency,
                    merchant_descriptor=merchant_descriptor,
                    institution=institution,
                )
                session.add(plaid_txn)
            else:
                plaid_txn.account_id = account_id
                plaid_txn.posted_at = posted_at
                plaid_txn.amount_cents = amount_cents
                plaid_txn.currency = currency
                plaid_txn.merchant_descriptor = merchant_descriptor
                plaid_txn.institution = institution
                plaid_txn.updated_at = datetime.now()

            session.flush()
            session.refresh(plaid_txn)
            session.expunge(plaid_txn)
            return plaid_txn

    def bulk_upsert_plaid_transactions(
        self,
        transactions: list[dict[str, Any]],
    ) -> list[int]:
        """Bulk insert or update Plaid transactions using PostgreSQL ON CONFLICT.

        Each dict should have keys:
            external_id, source, account_id, posted_at, amount_cents,
            currency, merchant_descriptor, institution

        Args:
            transactions: List of transaction dicts to upsert

        Returns:
            List of plaid_transaction_ids (in same order as input)
        """
        if not transactions:
            return []

        with self.session() as session:  # type: Session
            insert_stmt = pg_insert(PlaidTransaction).values(transactions)
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=["external_id", "source"],
                set_={
                    "account_id": insert_stmt.excluded.account_id,
                    "posted_at": insert_stmt.excluded.posted_at,
                    "amount_cents": insert_stmt.excluded.amount_cents,
                    "currency": insert_stmt.excluded.currency,
                    "merchant_descriptor": insert_stmt.excluded.merchant_descriptor,
                    "institution": insert_stmt.excluded.institution,
                    "updated_at": datetime.now(),
                },
            ).returning(PlaidTransaction.plaid_transaction_id)

            result = session.execute(stmt)
            plaid_ids = [row[0] for row in result.fetchall()]
            session.commit()
            return plaid_ids

    def get_plaid_transaction(
        self, plaid_transaction_id: int
    ) -> PlaidTransaction | None:
        """Get Plaid transaction by ID.

        Args:
            plaid_transaction_id: Plaid transaction ID

        Returns:
            PlaidTransaction instance or None if not found
        """
        with self.session() as session:  # type: Session
            plaid_txn = (
                session.query(PlaidTransaction)
                .filter(PlaidTransaction.plaid_transaction_id == plaid_transaction_id)
                .first()
            )
            if plaid_txn:
                session.expunge(plaid_txn)
            return plaid_txn

    def get_plaid_transactions_by_ids(
        self,
        plaid_transaction_ids: list[int],
    ) -> dict[int, PlaidTransaction]:
        """Get multiple Plaid transactions by IDs in a single query.

        Args:
            plaid_transaction_ids: List of Plaid transaction IDs

        Returns:
            Dict mapping plaid_transaction_id to PlaidTransaction instance
        """
        if not plaid_transaction_ids:
            return {}

        with self.session() as session:  # type: Session
            plaid_txns = (
                session.query(PlaidTransaction)
                .filter(
                    PlaidTransaction.plaid_transaction_id.in_(plaid_transaction_ids)
                )
                .all()
            )
            for txn in plaid_txns:
                session.expunge(txn)
            return {txn.plaid_transaction_id: txn for txn in plaid_txns}

    def delete_plaid_transactions_by_external_ids(
        self,
        external_ids: list[str],
        source: str = "PLAID",
    ) -> int:
        """Delete Plaid transactions by their external IDs.

        Cascade deletes to derived transactions automatically.

        Args:
            external_ids: List of external transaction IDs
            source: Source identifier (default: "PLAID")

        Returns:
            Number of transactions deleted
        """
        if not external_ids:
            return 0

        with self.session() as session:  # type: Session
            result = (
                session.query(PlaidTransaction)
                .filter(
                    PlaidTransaction.external_id.in_(external_ids),
                    PlaidTransaction.source == source,
                )
                .delete(synchronize_session=False)
            )
            return result

    # Derived Transactions methods

    def insert_derived_transaction(self, data: dict[str, Any]) -> DerivedTransaction:
        """Insert a new derived transaction.

        Args:
            data: Derived transaction data dictionary with fields:
                - plaid_transaction_id, external_id, amount_cents, posted_at
                - merchant_descriptor (optional), merchant_id (optional)
                - category_id (optional), is_verified (default: False)

        Returns:
            Created DerivedTransaction instance
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

            derived_txn = DerivedTransaction(
                plaid_transaction_id=data["plaid_transaction_id"],
                external_id=data["external_id"],
                amount_cents=data["amount_cents"],
                posted_at=data["posted_at"],
                merchant_descriptor=data.get("merchant_descriptor"),
                merchant_id=merchant_id,
                category_id=data.get("category_id"),
                is_verified=data.get("is_verified", False),
            )
            session.add(derived_txn)
            session.flush()
            session.refresh(derived_txn)
            session.expunge(derived_txn)
            return derived_txn

    def bulk_insert_derived_transactions(
        self,
        data_list: list[dict[str, Any]],
    ) -> list[int]:
        """Bulk insert derived transactions efficiently.

        Optimized for performance:
        - Single query to resolve existing merchants
        - Bulk creation of new merchants
        - Bulk insert of all derived transactions

        Args:
            data_list: List of derived transaction data dictionaries with fields:
                - plaid_transaction_id, external_id, amount_cents, posted_at
                - merchant_descriptor (optional), merchant_id (optional)
                - category_id (optional), is_verified (default: False)

        Returns:
            List of created transaction IDs
        """
        if not data_list:
            return []

        with self.session() as session:  # type: Session
            # Step 1: Collect unique merchant descriptors
            descriptors: set[str] = set()
            for data in data_list:
                if data.get("merchant_id") is None and data.get("merchant_descriptor"):
                    descriptors.add(
                        normalize_merchant_name(data["merchant_descriptor"])
                    )

            # Step 2: Fetch existing merchants in single query
            merchant_map: dict[str, int] = {}
            if descriptors:
                existing = (
                    session.query(Merchant)
                    .filter(Merchant.normalized_name.in_(descriptors))
                    .all()
                )
                for m in existing:
                    merchant_map[m.normalized_name] = m.merchant_id

            # Step 3: Create missing merchants
            new_merchants = []
            for data in data_list:
                if data.get("merchant_id") is None and data.get("merchant_descriptor"):
                    normalized = normalize_merchant_name(data["merchant_descriptor"])
                    if normalized not in merchant_map:
                        new_merchant = Merchant(
                            normalized_name=normalized,
                            display_name=data["merchant_descriptor"],
                        )
                        new_merchants.append(new_merchant)
                        merchant_map[normalized] = -1  # Placeholder

            if new_merchants:
                session.add_all(new_merchants)
                session.flush()
                # Update merchant_map with actual IDs
                for m in new_merchants:
                    merchant_map[m.normalized_name] = m.merchant_id

            # Step 4: Prepare derived transaction objects
            derived_txns = []
            for data in data_list:
                merchant_id = data.get("merchant_id")
                if merchant_id is None and data.get("merchant_descriptor"):
                    normalized = normalize_merchant_name(data["merchant_descriptor"])
                    merchant_id = merchant_map.get(normalized)

                derived_txn = DerivedTransaction(
                    plaid_transaction_id=data["plaid_transaction_id"],
                    external_id=data["external_id"],
                    amount_cents=data["amount_cents"],
                    posted_at=data["posted_at"],
                    merchant_descriptor=data.get("merchant_descriptor"),
                    merchant_id=merchant_id,
                    category_id=data.get("category_id"),
                    is_verified=data.get("is_verified", False),
                )
                derived_txns.append(derived_txn)

            # Step 5: Bulk insert
            session.add_all(derived_txns)
            session.flush()

            # Get IDs
            transaction_ids = [txn.transaction_id for txn in derived_txns]

            return transaction_ids

    def get_derived_by_plaid_id(
        self,
        plaid_transaction_id: int,
    ) -> list[DerivedTransaction]:
        """Get all derived transactions for a Plaid transaction.

        Args:
            plaid_transaction_id: Plaid transaction ID

        Returns:
            List of DerivedTransaction instances
        """
        with self.session() as session:  # type: Session
            derived_txns = (
                session.query(DerivedTransaction)
                .filter(DerivedTransaction.plaid_transaction_id == plaid_transaction_id)
                .all()
            )
            for txn in derived_txns:
                session.expunge(txn)
            return derived_txns

    def get_derived_by_plaid_ids(
        self,
        plaid_transaction_ids: list[int],
    ) -> dict[int, list[DerivedTransaction]]:
        """Get derived transactions for multiple Plaid transactions.

        Args:
            plaid_transaction_ids: List of Plaid transaction IDs

        Returns:
            Dict mapping plaid_transaction_id to list of DerivedTransaction instances
        """
        if not plaid_transaction_ids:
            return {}

        with self.session() as session:  # type: Session
            derived_txns = (
                session.query(DerivedTransaction)
                .filter(
                    DerivedTransaction.plaid_transaction_id.in_(plaid_transaction_ids)
                )
                .all()
            )
            for txn in derived_txns:
                session.expunge(txn)

            # Group by plaid_transaction_id
            result: dict[int, list[DerivedTransaction]] = {
                pid: [] for pid in plaid_transaction_ids
            }
            for txn in derived_txns:
                result[txn.plaid_transaction_id].append(txn)
            return result

    def get_derived_transactions_by_ids(
        self,
        transaction_ids: list[int],
    ) -> list[DerivedTransaction]:
        """Get derived transactions by IDs.

        Args:
            transaction_ids: List of transaction IDs

        Returns:
            List of DerivedTransaction instances
        """
        if not transaction_ids:
            return []

        with self.session() as session:  # type: Session
            derived_txns = (
                session.query(DerivedTransaction)
                .filter(DerivedTransaction.transaction_id.in_(transaction_ids))
                .order_by(DerivedTransaction.external_id)  # Deterministic for cache
                .all()
            )
            for txn in derived_txns:
                session.expunge(txn)
            return derived_txns

    def delete_derived_by_plaid_ids(
        self,
        plaid_transaction_ids: list[int],
    ) -> int:
        """Delete all derived transactions for multiple Plaid transactions.

        Args:
            plaid_transaction_ids: List of Plaid transaction IDs

        Returns:
            Number of transactions deleted
        """
        if not plaid_transaction_ids:
            return 0
        with self.session() as session:  # type: Session
            result = (
                session.query(DerivedTransaction)
                .filter(
                    DerivedTransaction.plaid_transaction_id.in_(plaid_transaction_ids)
                )
                .delete(synchronize_session=False)
            )
            return result

    def update_derived_category(
        self,
        transaction_id: int,
        category_id: int | None,
    ) -> None:
        """Update category of a derived transaction.

        Args:
            transaction_id: Transaction ID
            category_id: Category ID to set
        """
        with self.session() as session:  # type: Session
            derived_txn = (
                session.query(DerivedTransaction)
                .filter(DerivedTransaction.transaction_id == transaction_id)
                .first()
            )
            if derived_txn:
                derived_txn.category_id = category_id
                derived_txn.updated_at = datetime.now()

    def bulk_update_derived_categories(
        self,
        updates: dict[int, int],
    ) -> int:
        """Bulk update categories for multiple derived transactions.

        Performs all updates in a single database transaction for efficiency.

        Args:
            updates: Dictionary mapping transaction_id to category_id

        Returns:
            Number of transactions updated
        """
        if not updates:
            return 0

        with self.session() as session:  # type: Session
            now = datetime.now()
            # Build CASE expression for category_id
            case_expr = case(
                updates,
                value=DerivedTransaction.transaction_id,
            )
            # Update all matching transactions in single query
            result: int = (
                session.query(DerivedTransaction)
                .filter(DerivedTransaction.transaction_id.in_(updates.keys()))
                .update(
                    {
                        DerivedTransaction.category_id: case_expr,
                        DerivedTransaction.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            return result

    def update_derived_mutable(
        self,
        transaction_id: int,
        updates: dict[str, Any],
    ) -> DerivedTransaction:
        """Update mutable fields of a derived transaction.

        Only updates if transaction is not verified (is_verified=False).

        Args:
            transaction_id: Transaction ID to update
            updates: Dictionary of fields to update

        Returns:
            Updated DerivedTransaction instance

        Raises:
            ValueError: If transaction is verified and cannot be updated
        """
        with self.session() as session:  # type: Session
            derived_txn = (
                session.query(DerivedTransaction)
                .filter(DerivedTransaction.transaction_id == transaction_id)
                .first()
            )
            if derived_txn is None:
                raise ValueError(f"Derived transaction {transaction_id} not found")

            if derived_txn.is_verified:
                raise ValueError(
                    f"Transaction {transaction_id} is verified and immutable"
                )

            # Resolve merchant if merchant_descriptor is provided
            if "merchant_descriptor" in updates and updates["merchant_descriptor"]:
                normalized_name = normalize_merchant_name(
                    updates["merchant_descriptor"]
                )
                merchant = (
                    session.query(Merchant)
                    .filter(Merchant.normalized_name == normalized_name)
                    .first()
                )
                if merchant is None:
                    merchant = Merchant(
                        normalized_name=normalized_name,
                        display_name=updates["merchant_descriptor"],
                    )
                    session.add(merchant)
                    session.flush()
                updates["merchant_id"] = merchant.merchant_id

            # Update mutable fields
            for key, value in updates.items():
                if key in (
                    "category_id",
                    "merchant_id",
                    "amount_cents",
                    "merchant_descriptor",
                ):
                    setattr(derived_txn, key, value)

            derived_txn.updated_at = datetime.now()
            session.flush()
            session.refresh(derived_txn)
            session.expunge(derived_txn)
            return derived_txn

    def delete_plaid_item(self, item_id: str) -> bool:
        """Delete a Plaid item.

        Args:
            item_id: Plaid item ID to delete

        Returns:
            True if item was deleted, False if not found
        """
        with self.session() as session:  # type: Session
            item = session.query(PlaidItem).filter_by(item_id=item_id).first()
            if item is None:
                return False
            session.delete(item)
            return True


    # Migration methods

    def get_transactions_by_category_id(
        self, category_id: int
    ) -> list[DerivedTransaction]:
        """
        Get all transactions for a given category.

        Args:
            category_id: Category ID to filter by

        Returns:
            List of DerivedTransaction instances
        """
        with self.session() as session:  # type: Session
            txns = (
                session.query(DerivedTransaction)
                .filter_by(category_id=category_id)
                .all()
            )
            for txn in txns:
                session.expunge(txn)
            return txns

    def update_category_key(self, old_key: str, new_key: str) -> None:
        """
        Update category key (for rename operations).

        Args:
            old_key: Current category key
            new_key: New category key

        Raises:
            ValueError: If old_key does not exist or new_key already exists
        """
        with self.session() as session:  # type: Session
            old_category = session.query(Category).filter_by(key=old_key).first()
            if not old_category:
                msg = f"Category with key '{old_key}' does not exist"
                raise ValueError(msg)

            new_category = session.query(Category).filter_by(key=new_key).first()
            if new_category:
                msg = f"Category with key '{new_key}' already exists"
                raise ValueError(msg)

            old_category.key = new_key

    def reassign_transactions_to_category(
        self,
        transaction_ids: list[int],
        new_category_id: int,
        reset_verified: bool = False,
    ) -> None:
        """
        Bulk reassign transactions to new category, optionally reset verified status.

        Args:
            transaction_ids: List of transaction IDs to reassign
            new_category_id: New category ID to assign
            reset_verified: If True, set is_verified=False for these transactions

        Raises:
            ValueError: If new_category_id does not exist
        """
        if not transaction_ids:
            return

        with self.session() as session:  # type: Session
            # Validate category exists
            category = (
                session.query(Category).filter_by(category_id=new_category_id).first()
            )
            if not category:
                msg = f"Category with ID {new_category_id} does not exist"
                raise ValueError(msg)

            # Bulk update transactions
            for txn_id in transaction_ids:
                txn = (
                    session.query(DerivedTransaction)
                    .filter_by(transaction_id=txn_id)
                    .first()
                )
                if txn:
                    txn.category_id = new_category_id
                    if reset_verified:
                        txn.is_verified = False

    def replace_categories_from_taxonomy(self, taxonomy: Any) -> None:
        """
        Sync categories in DB with taxonomy contents, preserving category IDs.

        Used after taxonomy modifications to sync DB with in-memory taxonomy.
        Preserves existing category IDs to maintain foreign key integrity.

        Args:
            taxonomy: Taxonomy instance to sync from
        """
        with self.session() as session:  # type: Session
            # Get existing categories by key
            existing = {c.key: c for c in session.query(Category).all()}
            existing_keys = set(existing.keys())

            # Get new taxonomy nodes
            all_nodes = taxonomy.all_nodes()
            new_keys = {n.key for n in all_nodes}

            # Delete categories no longer in taxonomy
            keys_to_delete = existing_keys - new_keys
            for key in keys_to_delete:
                session.delete(existing[key])
            session.flush()

            # Build parent_id mapping (existing + new)
            parent_id_map: dict[str, int] = {}
            for key, cat in existing.items():
                if key in new_keys:
                    parent_id_map[key] = cat.category_id

            # Process nodes: parents first, then children
            parent_nodes = [n for n in all_nodes if n.parent_key is None]
            child_nodes = [n for n in all_nodes if n.parent_key is not None]

            # Update or insert parents
            for node in parent_nodes:
                if node.key in existing:
                    # Update existing
                    cat = existing[node.key]
                    cat.name = node.name
                    cat.description = node.description
                    cat.parent_id = None
                else:
                    # Insert new
                    cat = Category(
                        key=node.key,
                        name=node.name,
                        description=node.description,
                        parent_id=None,
                    )
                    session.add(cat)
                    session.flush()
                    parent_id_map[node.key] = cat.category_id

            # Update or insert children
            for node in child_nodes:
                parent_id = (
                    parent_id_map.get(node.parent_key) if node.parent_key else None
                )
                if node.key in existing:
                    # Update existing
                    cat = existing[node.key]
                    cat.name = node.name
                    cat.description = node.description
                    cat.parent_id = parent_id
                else:
                    # Insert new
                    cat = Category(
                        key=node.key,
                        name=node.name,
                        description=node.description,
                        parent_id=parent_id,
                    )
                    session.add(cat)
                    session.flush()
                    parent_id_map[node.key] = cat.category_id
