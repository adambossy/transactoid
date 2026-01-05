from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import TypedDict

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Date,
    ForeignKey,
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

    category_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.category_id"), nullable=True
    )
    key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
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
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

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
