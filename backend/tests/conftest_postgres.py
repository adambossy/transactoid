"""The ``pg_db`` fixture backing the @pytest.mark.postgres suites.

Not auto-collected (pytest only imports files named exactly ``conftest.py``);
``tests/conftest.py`` re-exports the fixture. Skips unless POSTGRES_TEST_URL
is set — point it at the Neon ``penny-test`` branch or a local Postgres,
never at prod.
"""

from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa

from penny.adapters.db.facade import DB
from penny.adapters.db.rls import enable_rls


@pytest.fixture
def pg_db():
    url = os.environ.get("POSTGRES_TEST_URL", "").strip()
    if not url:
        pytest.skip("POSTGRES_TEST_URL not set")
    # Unique schema per test: full isolation, trivially dropped.
    schema = f"t_{uuid.uuid4().hex[:8]}"
    admin = DB(url)
    with admin.session() as s:
        s.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    sep = "&" if "?" in url else "?"
    db = DB(f"{url}{sep}options=-csearch_path%3D{schema}")
    db.create_schema()
    with db._engine.begin() as conn:
        enable_rls(conn)
    yield db
    db._engine.dispose()
    with admin.session() as s:
        s.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin._engine.dispose()
