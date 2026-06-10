from __future__ import annotations

from collections.abc import Iterator

import pytest

from penny.db import get_db


@pytest.fixture(autouse=True)
def _create_schema(isolated_db: None) -> Iterator[None]:
    """Create the full schema for each test that uses isolated_db."""
    get_db().create_schema()
    yield
