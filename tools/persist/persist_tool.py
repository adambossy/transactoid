from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApplyTagsOutcome:
    applied: int
    created_tags: list[str]


class PersistTool:
    def __init__(self, db: "DB", taxonomy: "Taxonomy") -> None:
        self._db = db
        self._taxonomy = taxonomy

    def bulk_recategorize_by_merchant(
        self,
        merchant_id: int,
        category_key: str,
        *,
        only_unverified: bool = True,
    ) -> int:
        # Minimal stub: no rows affected
        return 0

    def apply_tags(
        self, transaction_ids: list[int], tag_names: list[str]
    ) -> ApplyTagsOutcome:
        # Minimal stub: nothing applied, echo requested tags as created for visibility
        return ApplyTagsOutcome(applied=0, created_tags=list(tag_names))
