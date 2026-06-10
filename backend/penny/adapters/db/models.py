from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import TypedDict

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    pass


class Merchant(Base):
    """Merchant model."""

    __tablename__ = "merchants"

    merchant_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    normalized_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    transactions: Mapped[list[DerivedTransaction]] = relationship(
        "DerivedTransaction", back_populates="merchant"
    )


class Category(Base):
    """Category model."""

    __tablename__ = "categories"
    __table_args__ = (
        Index(
            "uq_categories_key_active",
            "key",
            unique=True,
            postgresql_where=text("deprecated_at IS NULL"),
            sqlite_where=text("deprecated_at IS NULL"),
        ),
    )

    category_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.category_id"), nullable=True
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rules: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON array stored as TEXT
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    # Relationships
    parent: Mapped[Category | None] = relationship(
        "Category", remote_side="Category.category_id", back_populates="children"
    )
    children: Mapped[list[Category]] = relationship("Category", back_populates="parent")
    transactions: Mapped[list[DerivedTransaction]] = relationship(
        "DerivedTransaction", back_populates="category"
    )


class PlaidTransaction(Base):
    """Plaid Transaction model - immutable source data from Plaid."""

    __tablename__ = "plaid_transactions"
    __table_args__ = (
        UniqueConstraint(
            "external_id", "source", name="uq_plaid_transactions_external_source"
        ),
    )

    plaid_transaction_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "PLAID" or "CSV"
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("plaid_items.item_id", ondelete="CASCADE"), nullable=True
    )
    posted_at: Mapped[date] = mapped_column(Date, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    merchant_descriptor: Mapped[str | None] = mapped_column(Text, nullable=True)
    institution: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    plaid_item: Mapped[PlaidItem | None] = relationship(
        "PlaidItem", back_populates="transactions"
    )
    derived_transactions: Mapped[list[DerivedTransaction]] = relationship(
        "DerivedTransaction",
        back_populates="plaid_transaction",
        cascade="all, delete-orphan",
    )


class DerivedTransaction(Base):
    """Derived Transaction model - mutable, enriched transactions for queries."""

    __tablename__ = "derived_transactions"
    __table_args__ = (
        CheckConstraint(
            "category_method IS NULL OR category_method IN "
            "('llm', 'manual', 'taxonomy_migration')",
            name="ck_derived_transactions_category_method",
        ),
        CheckConstraint(
            "(category_id IS NULL AND category_method IS NULL "
            "AND category_assigned_at IS NULL) OR "
            "(category_id IS NOT NULL AND category_method IS NOT NULL "
            "AND category_assigned_at IS NOT NULL)",
            name="ck_derived_transactions_category_provenance_consistency",
        ),
        # NOTE: Any values listed here must also be listed in the migration's PostgreSQL
        # op.create_check_constraint call for ck_derived_transactions_split_source.
        # SQLite enforces this constraint via the ORM; PostgreSQL via the migration.
        CheckConstraint(
            "split_source IS NULL OR split_source IN "
            "('user_split', 'amazon_mutation', 'email_mutation')",
            name="ck_derived_transactions_split_source",
        ),
        # NOTE: Any values listed here must also be listed in the migration's PostgreSQL
        # op.create_check_constraint call for ck_derived_transactions_refund_matched_by.
        # SQLite enforces this constraint via the ORM; PostgreSQL via the migration.
        CheckConstraint(
            "refund_matched_by IS NULL OR refund_matched_by IN ('user', 'auto')",
            name="ck_derived_transactions_refund_matched_by",
        ),
        # NOTE: This constraint must also be listed in the migration's PostgreSQL
        # op.create_check_constraint call for
        # ck_derived_transactions_refund_consistency.
        # SQLite enforces this constraint via the ORM; PostgreSQL via the migration.
        CheckConstraint(
            "(refund_of_transaction_id IS NULL "
            "AND refund_matched_by IS NULL "
            "AND refund_matched_at IS NULL) OR "
            "(refund_of_transaction_id IS NOT NULL "
            "AND refund_matched_by IS NOT NULL "
            "AND refund_matched_at IS NOT NULL)",
            name="ck_derived_transactions_refund_consistency",
        ),
    )

    transaction_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    plaid_transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("plaid_transactions.plaid_transaction_id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    posted_at: Mapped[date] = mapped_column(Date, nullable=False)
    merchant_descriptor: Mapped[str | None] = mapped_column(Text, nullable=True)
    merchant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("merchants.merchant_id"), nullable=True
    )
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.category_id"), nullable=True
    )
    category_model: Mapped[str | None] = mapped_column(String, nullable=True)
    category_method: Mapped[str | None] = mapped_column(String, nullable=True)
    category_assigned_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, nullable=True
    )
    web_search_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    reporting_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    split_group_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    split_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    split_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Refund linkage columns (all nullable; existing rows unaffected).
    # A refund row is a negative-amount derived_transactions row. The FK points
    # from the refund row to the original positive-amount charge it offsets.
    # ON DELETE SET NULL: if the original is deleted the refund row survives but
    # loses its link — auditable orphan rather than silent cascade loss.
    refund_of_transaction_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("derived_transactions.transaction_id", ondelete="SET NULL"),
        nullable=True,
    )
    refund_matched_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_matched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)

    # Relationships
    plaid_transaction: Mapped[PlaidTransaction] = relationship(
        "PlaidTransaction", back_populates="derived_transactions"
    )
    merchant: Mapped[Merchant | None] = relationship(
        "Merchant", back_populates="transactions"
    )
    category: Mapped[Category | None] = relationship(
        "Category", back_populates="transactions"
    )
    tags: Mapped[list[Tag]] = relationship(
        "Tag", secondary="transaction_tags", back_populates="transactions"
    )
    category_events: Mapped[list[TransactionCategoryEvent]] = relationship(
        "TransactionCategoryEvent",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionCategoryEvent.created_at",
    )
    items: Mapped[list[TransactionItem]] = relationship(
        "TransactionItem",
        back_populates="derived_transaction",
        cascade="all, delete-orphan",
    )
    # Self-referential relationship: refund_of points to the original charge.
    # remote_side=[transaction_id] tells SQLAlchemy that the "one" side of the
    # one-to-many is the transaction_id column of the *same* table.
    refund_of: Mapped[DerivedTransaction | None] = relationship(
        "DerivedTransaction",
        foreign_keys=[refund_of_transaction_id],
        remote_side="DerivedTransaction.transaction_id",
        back_populates="refunds",
    )
    refunds: Mapped[list[DerivedTransaction]] = relationship(
        "DerivedTransaction",
        foreign_keys="DerivedTransaction.refund_of_transaction_id",
        back_populates="refund_of",
    )


class TransactionCategoryEvent(Base):
    """Append-only history of category changes for a transaction."""

    __tablename__ = "transaction_category_events"
    __table_args__ = (
        CheckConstraint(
            "method IN ('llm', 'manual', 'taxonomy_migration')",
            name="ck_transaction_category_events_method",
        ),
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("derived_transactions.transaction_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.category_id"), nullable=True
    )
    to_category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.category_id"), nullable=False
    )
    from_category_key: Mapped[str | None] = mapped_column(String, nullable=True)
    to_category_key: Mapped[str] = mapped_column(String, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    transaction: Mapped[DerivedTransaction] = relationship(
        "DerivedTransaction", back_populates="category_events"
    )
    from_category: Mapped[Category | None] = relationship(
        "Category", foreign_keys=[from_category_id]
    )
    to_category: Mapped[Category] = relationship(
        "Category", foreign_keys=[to_category_id]
    )


class Tag(Base):
    """Tag model."""

    __tablename__ = "tags"

    tag_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    transactions: Mapped[list[DerivedTransaction]] = relationship(
        "DerivedTransaction", secondary="transaction_tags", back_populates="tags"
    )


class TransactionTag(Base):
    """Transaction-Tag junction table."""

    __tablename__ = "transaction_tags"

    transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("derived_transactions.transaction_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.tag_id"), primary_key=True
    )


class PlaidItem(Base):
    """Plaid Item model for storing access tokens and item information."""

    __tablename__ = "plaid_items"

    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    institution_id: Mapped[str | None] = mapped_column(String, nullable=True)
    institution_name: Mapped[str | None] = mapped_column(String, nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    investments_synced_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    transactions: Mapped[list[PlaidTransaction]] = relationship(
        "PlaidTransaction", back_populates="plaid_item", cascade="all, delete-orphan"
    )


class CategoryRow(TypedDict):
    category_id: int
    parent_id: int | None
    key: str
    name: str
    description: str | None
    parent_key: str | None
    deprecated_at: datetime | None


@dataclass
class SaveRowOutcome:
    external_id: str
    source: str  # "CSV" | "PLAID"
    action: str  # "inserted" | "updated" | "skipped-verified" | "skipped-duplicate"
    transaction_id: int | None = None
    reason: str | None = None


@dataclass
class SaveOutcome:
    inserted: int
    updated: int
    skipped_verified: int
    skipped_duplicate: int
    rows: list[SaveRowOutcome]


def normalize_merchant_name(descriptor: str) -> str:
    """Normalize merchant descriptor for matching.

    Uses the same logic as tools/ingest/adapters/amex.py:
    - Lowercase and trim
    - Remove digits
    - Collapse whitespace
    """
    lowered = descriptor.lower().strip()
    no_digits = re.sub(r"\d+", "", lowered)
    collapsed = re.sub(r"\s+", " ", no_digits).strip()
    return collapsed


class AmazonOrderDB(Base):
    """Amazon order scraped from order history."""

    __tablename__ = "amazon_orders"

    order_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("amazon_login_profiles.profile_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    shipping_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationship
    items: Mapped[list["AmazonItemDB"]] = relationship(  # noqa: UP037
        "AmazonItemDB", back_populates="order"
    )


class AmazonItemDB(Base):
    """Amazon item scraped from order history."""

    __tablename__ = "amazon_items"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("amazon_orders.order_id"), nullable=False
    )
    asin: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationship
    order: Mapped[AmazonOrderDB] = relationship("AmazonOrderDB", back_populates="items")

    __table_args__ = (
        UniqueConstraint("order_id", "asin", name="uq_amazon_item_order_asin"),
    )


class AmazonLoginProfileDB(Base):
    """Amazon login profile for multi-account scraping."""

    __tablename__ = "amazon_login_profiles"

    profile_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    profile_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    browserbase_context_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_auth_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_auth_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_auth_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    history_complete_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class TransactionItem(Base):
    """A single line item within a transaction, from Amazon, email, or manual entry."""

    __tablename__ = "transaction_items"
    # NOTE: Any values listed here must also be listed in the migration's PostgreSQL
    # op.create_check_constraint call for ck_transaction_items_itemization_source.
    # SQLite enforces this constraint via the ORM; PostgreSQL via the migration.
    __table_args__ = (
        CheckConstraint(
            "itemization_source IN ('amazon_scrape', 'email_receipt', 'manual')",
            name="ck_transaction_items_itemization_source",
        ),
    )

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("derived_transactions.transaction_id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    itemization_source: Mapped[str] = mapped_column(Text, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    derived_transaction: Mapped[DerivedTransaction] = relationship(
        "DerivedTransaction", back_populates="items"
    )


class EmailReceipt(Base):
    """Parsed Gmail receipt — dedup and audit record for the email-receipt pipeline.

    message_id is the Gmail message identifier and the dedup key.
    subject and sender are captured for diagnostics and allowlist matching only;
    do NOT include them in logs, cache payloads, or LLM prompts. Both are capped
    at 2048 characters to prevent oversize-input issues in the parsing path.
    The itemization data produced from a matched receipt lives in
    transaction_items with itemization_source='email_receipt' and
    source_ref=message_id.
    """

    __tablename__ = "email_receipts"

    receipt_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    message_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP,
        nullable=True,
        # Gmail `internalDate` (when Gmail ingested the message) converted to UTC.
        # NOT the `Date:` RFC 5322 header from the sender's mail server (that field
        # is sender-controlled and unreliable). Used by the matcher to compute
        # `date_lag_days` against `derived_transactions.posted_at`.
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    pending_matches: Mapped[list[PendingReceiptMatch]] = relationship(
        "PendingReceiptMatch",
        back_populates="email_receipt",
        cascade="all, delete-orphan",
    )


class AccountSignConvention(Base):
    """Per-account sign convention lookup.

    Records whether a Plaid account reports expenses as positive amounts
    ('expense_positive') or negative amounts ('expense_negative').

    account_id matches plaid_transactions.account_id. There is no FK because
    the plaid_accounts table was dropped in an earlier migration.

    Rows are normally populated automatically by the seeding pipeline;
    manual overrides are recorded with provenance='manual'.

    NOTE: The CHECK constraint values here must match the migration's
    CREATE TABLE CHECK constraints. If the allowed values change, update
    BOTH this model AND migration 004.
    """

    __tablename__ = "account_sign_conventions"
    __table_args__ = (
        CheckConstraint(
            "sign_convention IN ('expense_positive', 'expense_negative')",
            name="ck_account_sign_conventions_sign_convention",
        ),
        CheckConstraint(
            "provenance IN ('seeded', 'manual')",
            name="ck_account_sign_conventions_provenance",
        ),
    )

    account_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sign_convention: Mapped[str] = mapped_column(Text, nullable=False)
    provenance: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PendingReceiptMatch(Base):
    """Low-confidence email-receipt candidate queued for human review.

    transaction_items rows are NOT written until status='confirmed'.
    match_score is a composite 0.0..1.0 value; lower means more uncertain.

    The UNIQUE constraint on (message_id, candidate_txn_id) enforces "one
    match-attempt per (message_id, candidate_txn_id) pair." Status transitions
    (pending -> confirmed, pending -> rejected, rejected -> pending) are
    implemented as UPDATE on the existing row, NOT INSERT of a new one. The
    row's status, resolved_at, and match_score may be mutated, but the row
    identity is stable. PR #6 owns the workflow implementation.

    Recovery: if the parent EmailReceipt is re-parsed (e.g., parser improvement),
    delete-then-reinsert of the EmailReceipt cascades and re-queues all matches.

    NOTE: Any values listed here must also be listed in the migration's PostgreSQL
    op.create_check_constraint call for ck_pending_receipt_matches_status.
    SQLite enforces this constraint via the ORM; PostgreSQL via the migration.
    """

    __tablename__ = "pending_receipt_matches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name="ck_pending_receipt_matches_status",
        ),
        UniqueConstraint(
            "message_id",
            "candidate_txn_id",
            name="uq_pending_receipt_matches_message_candidate",
        ),
    )

    pending_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    # FK to email_receipts.message_id (the natural key, not the surrogate receipt_id
    # PK) for parity with transaction_items.source_ref, which also stores the Gmail
    # message_id. Lets the web UI join pending_receipt_matches and transaction_items
    # directly on the same identifier.
    message_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("email_receipts.message_id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_txn_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("derived_transactions.transaction_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Snapshot of the receipt-side amount at the time the candidate was queued.
    # Never updated. If the receipt is re-parsed (e.g., parser improvement),
    # recovery is delete-then-reinsert of the parent EmailReceipt, which cascades
    # and re-queues. Display value for the review UI; not the matching threshold.
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    date_lag_days: Mapped[int] = mapped_column(Integer, nullable=False)
    match_score: Mapped[float] = mapped_column(Float(), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    email_receipt: Mapped[EmailReceipt] = relationship(
        "EmailReceipt", back_populates="pending_matches"
    )
    candidate_transaction: Mapped[DerivedTransaction] = relationship(
        "DerivedTransaction", foreign_keys=[candidate_txn_id]
    )
