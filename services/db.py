from __future__ import annotations

from typing import Any, ContextManager, Dict, List, Optional, Type, TypeVar

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


class DB:
    def __init__(self, url: str) -> None:
        self._url = url

    def session(self) -> ContextManager[Any]:
        raise NotImplementedError("Session management is not implemented in stub.")

    def run_sql(
        self,
        sql: str,
        *,
        model: Type[M],
        pk_column: str,
    ) -> List[M]:
        # Minimal stub: no rows returned
        return []

    def fetch_transactions_by_ids_preserving_order(
        self, ids: List[int]
    ) -> List[Transaction]:
        return []

    def get_category_id_by_key(self, key: str) -> Optional[int]:
        return None

    def find_merchant_by_normalized_name(
        self, normalized_name: str
    ) -> Optional[Merchant]:
        return None

    def create_merchant(
        self, *, normalized_name: str, display_name: Optional[str]
    ) -> Merchant:
        raise NotImplementedError("create_merchant is not implemented in stub.")

    def get_transaction_by_external(
        self, *, external_id: str, source: str
    ) -> Optional[Transaction]:
        return None

    def insert_transaction(self, data: Dict[str, Any]) -> Transaction:
        raise NotImplementedError("insert_transaction is not implemented in stub.")

    def update_transaction_mutable(
        self, transaction_id: int, data: Dict[str, Any]
    ) -> Transaction:
        raise NotImplementedError(
            "update_transaction_mutable is not implemented in stub."
        )

    def recategorize_unverified_by_merchant(
        self, merchant_id: int, category_id: int
    ) -> int:
        return 0

    def upsert_tag(self, name: str, description: Optional[str] = None) -> Tag:
        raise NotImplementedError("upsert_tag is not implemented in stub.")

    def attach_tags(self, transaction_ids: List[int], tag_ids: List[int]) -> int:
        return 0

    def compact_schema_hint(self) -> Dict[str, Any]:
        return {}

    # Helper used by Taxonomy.from_db() in tests
    def fetch_categories(self) -> List[Dict[str, Any]]:
        return []
