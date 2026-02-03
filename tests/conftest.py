"""Shared test fixtures."""

from __future__ import annotations

import pytest

from transactoid.taxonomy.loader import clear_category_id_cache


@pytest.fixture(autouse=True)
def _clear_category_cache() -> None:
    """Clear the category ID cache before each test.

    The in-process cache in taxonomy.loader persists across tests,
    causing stale lookups when different tests use different in-memory DBs.
    """
    clear_category_id_cache()
