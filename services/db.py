from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Any, TypedDict, TypeVar, cast

M = TypeVar("M")


class Merchant: ...


class Category:
    # Fields: category_id, parent_id, key, name, description, rules
    ...


class Transaction:
    # Includes merchant_descriptor, institution, is_verified, etc.
    ...


class Tag: ...


class TransactionTag: ...


class CategoryRow(TypedDict):
    category_id: int
    parent_id: int | None
    key: str
    name: str
    description: str | None
    parent_key: str | None


class DB:
    def __init__(self, url: str) -> None:
        self._url = url
        self._category_rows: list[CategoryRow] = []
        self._category_index: dict[str, CategoryRow] = {}

    def session(self) -> AbstractContextManager[Any]:
        raise NotImplementedError("Session management is not implemented in stub.")

    def run_sql(
        self,
        sql: str,
        *,
        model: type[M],
        pk_column: str,
    ) -> list[M]:
        return []

    def fetch_transactions_by_ids_preserving_order(
        self,
        ids: list[int],
    ) -> list[Transaction]:
        return []

    def get_category_id_by_key(self, key: str) -> int | None:
        row = self._category_index.get(key)
        if row is None:
            return None
        category_id = row.get("category_id")
        return int(category_id) if isinstance(category_id, int) else None

    def find_merchant_by_normalized_name(self, normalized_name: str) -> Merchant | None:
        return None

    def create_merchant(
        self,
        *,
        normalized_name: str,
        display_name: str | None,
    ) -> Merchant:
        raise NotImplementedError("create_merchant is not implemented in stub.")

    def get_transaction_by_external(
        self,
        *,
        external_id: str,
        source: str,
    ) -> Transaction | None:
        return None

    def insert_transaction(self, data: dict[str, Any]) -> Transaction:
        raise NotImplementedError("insert_transaction is not implemented in stub.")

    def update_transaction_mutable(
        self,
        transaction_id: int,
        data: dict[str, Any],
    ) -> Transaction:
        raise NotImplementedError(
            "update_transaction_mutable is not implemented in stub."
        )

    def recategorize_unverified_by_merchant(
        self,
        merchant_id: int,
        category_id: int,
    ) -> int:
        return 0

    def upsert_tag(self, name: str, description: str | None = None) -> Tag:
        raise NotImplementedError("upsert_tag is not implemented in stub.")

    def attach_tags(self, transaction_ids: list[int], tag_ids: list[int]) -> int:
        return 0

    def compact_schema_hint(self) -> dict[str, Any]:
        return {}

    def fetch_categories(self) -> list[CategoryRow]:
        return self._category_rows.copy()

    def replace_categories_rows(self, rows: Sequence[CategoryRow]) -> None:
        """
        Replace categories with pre-built rows (ids and parent ids already resolved).
        """
        # Make a shallow copy to avoid external mutation and rebuild index.
        self._category_rows = [cast(CategoryRow, dict(row)) for row in rows]
        self._category_index = {row["key"]: row for row in self._category_rows}
