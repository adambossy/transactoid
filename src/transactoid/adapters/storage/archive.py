"""Archival utilities for investment duplicate cleanup."""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
from typing import Any

from loguru import logger

from transactoid.adapters.storage.r2 import R2StorageError, store_object_in_r2


def archive_investment_dupes_to_r2(
    *,
    item_id: str,
    records: list[dict[str, Any]],
    key_prefix: str = "investment-dedup",
) -> None:
    """Archive investment duplicate records to R2 for auditability.

    Serializes *records* to JSON and uploads under
    ``{key_prefix}/{item_id}/{YYYYMMDD}T{HHMMSS}Z.json``.

    Swallows ``R2StorageError`` with a warning log so callers are never
    blocked by archival failure.

    Args:
        item_id: Plaid item ID.
        records: List of dicts to archive (must be JSON-serializable
            after date conversion).
        key_prefix: R2 key prefix (default ``investment-dedup``).
    """
    now = datetime.now(UTC)
    ts_str = now.strftime("%Y%m%dT%H%M%SZ")
    key = f"{key_prefix}/{item_id}/{ts_str}.json"

    serializable: list[dict[str, Any]] = []
    for record in records:
        converted: dict[str, Any] = {}
        for k, v in record.items():
            if isinstance(v, dict):
                inner: dict[str, Any] = {}
                for ik, iv in v.items():
                    inner[ik] = iv.isoformat() if isinstance(iv, date) else iv
                converted[k] = inner
            elif isinstance(v, date):
                converted[k] = v.isoformat()
            else:
                converted[k] = v
        serializable.append(converted)

    body = json.dumps(serializable, indent=2).encode("utf-8")

    try:
        store_object_in_r2(
            key=key,
            body=body,
            content_type="application/json",
        )
    except R2StorageError:
        logger.warning(
            "Failed to archive {} investment dupes to R2 key {}",
            len(records),
            key,
        )
