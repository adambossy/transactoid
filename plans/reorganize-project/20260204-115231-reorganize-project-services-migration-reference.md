# Services Migration Quick Reference

## Complete File Mapping

| Current Path | New Path | Size | Type | Notes |
|---|---|---|---|---|
| `services/__init__.py` | Delete | — | Config | No exports; callers import directly |
| `services/yaml_utils.py` | `src/transactoid/utils/yaml.py` | 57 lines | Utility | Pure util; no deps. Rename: keep as `yaml.py` |
| `services/file_cache.py` | `src/transactoid/infrastructure/cache/file_cache.py` | 170 lines | Service | Self-contained cache impl |
| `services/plaid_link_flow.py` | `src/transactoid/infrastructure/clients/plaid_link.py` | ~300 lines | Service | OAuth flow; rename for clarity |
| `services/plaid_client.py` | `src/transactoid/infrastructure/clients/plaid.py` | ~450 lines | Service | Main Plaid API client |
| `services/taxonomy.py` | **SPLIT** (see below) | 120 lines | Domain | Domain logic only; remove DB coupling |
| `services/taxonomy_generator.py` | `src/transactoid/taxonomy/generator.py` | ~200 lines | Service | YAML → Taxonomy; no changes |
| `services/db.py` | **SPLIT** (see below) | 1000+ lines | Service | Split into models + facade |

---

## services/db.py → SPLIT: Models and Facade

### Part 1: ORM Models Only

**Destination**: `src/transactoid/infrastructure/db/models.py`

**Contents** (lines from original):
```
- class Base(DeclarativeBase)           [40-43]
- class Merchant(Base)                  [46-66]
- class Category(Base)                  [69-101]
- class Transaction(Base)               [103-150]
- class Tag(Base)                       [152-171]
- class TransactionTag(Base)            [173-184]
- class PlaidItem(Base)                 [186-201]
- class CategoryRow(TypedDict)          [203-209]
```

**Size**: ~160 lines

**Imports needed**:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import TypedDict
from sqlalchemy import (TIMESTAMP, Boolean, Date, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine, text)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column,
                            relationship, sessionmaker)
```

**Zero business logic** ✓

---

### Part 2: DB Service Layer (Refactored)

**Destination**: `src/transactoid/infrastructure/db/facade.py`

**Contents** (lines from original, refactored):
```
- class SaveRowOutcome                  [213-218]
- class SaveOutcome                     [222-227]
- function _normalize_merchant_name()   [230-241]
- class DB:
  - __init__()                          [247-255]
  - session()                           [257-268]
  - execute_raw_sql()                   [270-284]
  - run_sql()                           [286-331]
  - fetch_transactions_by_ids_preserving_order()   [333-366]
  - get_category_id_by_key()            [368-379]
  - find_merchant_by_normalized_name()  [381-398]
  - create_merchant()                   [400-423]
  - get_transaction_by_external()       [425-450]
  - insert_transaction()                [452-500]
  - update_transaction_mutable()        [501-544]
  - recategorize_unverified_by_merchant() [546-569]
  - upsert_tag()                        [571-592]
  - attach_tags()                       [594-630]
  - delete_transactions_by_external_ids() [632-661]
  - save_transactions()  [REFACTORED]   [663-808]
  - compact_schema_hint()               [810-879]
  - fetch_categories()                  [881-910]
  - replace_categories_rows()           [912-934]
  - save_plaid_item()                   [936-973]
  - get_plaid_item()                    [975-988]
  - list_plaid_items()                  [990-1000]
```

**Size**: ~850 lines (after refactoring save_transactions)

**Imports needed**:
```python
from __future__ import annotations
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any, TypeVar, cast

from sqlalchemy import (TIMESTAMP, Boolean, Date, ForeignKey, Integer, String, Text,
                        UniqueConstraint, case, create_engine, text)
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import (Session, sessionmaker)

from src.transactoid.infrastructure.db.models import (
    Base, Merchant, Category, Transaction, Tag, TransactionTag, PlaidItem, CategoryRow
)
```

**Key refactoring**:

**Before**:
```python
def save_transactions(
    self,
    taxonomy: Taxonomy,  # ← removed
    txns: Iterable[CategorizedTransaction],
) -> SaveOutcome:
    for cat_txn in txns:
        category_id = taxonomy.category_id_for_key(self, category_key)
```

**After**:
```python
def save_transactions(
    self,
    category_lookup: Callable[[str], int | None],  # ← injected callback
    txns: Iterable[CategorizedTransaction],
) -> SaveOutcome:
    for cat_txn in txns:
        category_id = category_lookup(category_key)  # ← use callback
```

---

## services/taxonomy.py → SPLIT: Core + Loader

### Part 1: Pure Domain Logic

**Destination**: `src/transactoid/taxonomy/core.py`

**Contents** (modified; removes DB methods):
```python
from __future__ import annotations
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

@dataclass(frozen=True)
class CategoryNode:
    key: str
    name: str
    description: str | None
    parent_key: str | None

class Taxonomy:
    @staticmethod
    def _node_sort_key(node: CategoryNode) -> str:
        return node.key

    def __init__(self, nodes: Sequence[CategoryNode]) -> None:
        self._nodes_by_key: dict[str, CategoryNode] = {n.key: n for n in nodes}
        self._children: dict[str, list[CategoryNode]] = {}
        for node in nodes:
            if node.parent_key:
                self._children.setdefault(node.parent_key, []).append(node)
        # Ensure deterministic ordering
        for key in list(self._children.keys()):
            self._children[key].sort(key=self._node_sort_key)

    @classmethod
    def from_nodes(cls, nodes: Sequence[CategoryNode]) -> Taxonomy:
        """Build Taxonomy from pre-loaded nodes (dependency injection)."""
        return cls(sorted(nodes, key=cls._node_sort_key))

    def is_valid_key(self, key: str) -> bool:
        return key in self._nodes_by_key

    def get(self, key: str) -> CategoryNode | None:
        return self._nodes_by_key.get(key)

    def children(self, key: str) -> list[CategoryNode]:
        return list(self._children.get(key, []))

    def parent(self, key: str) -> CategoryNode | None:
        node = self._nodes_by_key.get(key)
        if node is None or node.parent_key is None:
            return None
        return self._nodes_by_key.get(node.parent_key)

    def parents(self) -> list[CategoryNode]:
        roots = [n for n in self._nodes_by_key.values() if n.parent_key is None]
        roots.sort(key=lambda n: n.key)
        return roots

    def all_nodes(self) -> list[CategoryNode]:
        return [self._nodes_by_key[k] for k in sorted(self._nodes_by_key.keys())]

    def to_prompt(self, *, include_keys: Iterable[str] | None = None) -> dict[str, object]:
        if include_keys is None:
            selected = self.all_nodes()
        else:
            wanted = set(include_keys)
            selected = [n for n in self.all_nodes() if n.key in wanted]
        nodes_payload: list[dict[str, object]] = []
        for n in selected:
            nodes_payload.append({
                "key": n.key,
                "name": n.name,
                "description": n.description,
                "parent_key": n.parent_key,
            })
        return {"nodes": nodes_payload}

    def path_str(self, key: str, sep: str = " > ") -> str | None:
        node = self._nodes_by_key.get(key)
        if node is None:
            return None
        parts: list[str] = [node.name]
        parent = self.parent(key)
        if parent is not None:
            parts.insert(0, parent.name)
        return sep.join(parts)
```

**Removed**:
- `from services.db import DB` ✓
- `@classmethod def from_db(cls, db: DB)` ✓
- `def category_id_for_key(self, db: DB, key: str)` ✓

**Size**: ~100 lines

---

### Part 2: DB ↔ Taxonomy Bridge (NEW FILE)

**Destination**: `src/transactoid/taxonomy/loader.py` (NEW)

**Contents**:
```python
"""Taxonomy loader: instantiates Taxonomy from database."""

from __future__ import annotations

from src.transactoid.taxonomy.core import Taxonomy, CategoryNode
from src.transactoid.infrastructure.db.facade import DB


def load_taxonomy_from_db(db: DB) -> Taxonomy:
    """Load taxonomy from database.

    Args:
        db: Database facade instance

    Returns:
        Constructed Taxonomy object

    Raises:
        Exception: If database fetch fails
    """
    rows = db.fetch_categories()
    nodes: list[CategoryNode] = []
    for row in rows:
        nodes.append(
            CategoryNode(
                key=str(row["key"]),
                name=str(row["name"]),
                description=(
                    None
                    if row.get("description") is None
                    else str(row["description"])
                ),
                parent_key=(
                    None
                    if row.get("parent_key") is None
                    else str(row["parent_key"])
                ),
            )
        )
    # Sort to keep stable order
    nodes_sorted = sorted(nodes, key=lambda n: n.key)
    return Taxonomy.from_nodes(nodes_sorted)


def get_category_id(db: DB, taxonomy: Taxonomy, key: str) -> int | None:
    """Look up category ID from DB using Taxonomy validation.

    This method replaces Taxonomy.category_id_for_key(self, db).
    Now it's explicit: you need both Taxonomy AND DB together.

    Args:
        db: Database facade instance
        taxonomy: Taxonomy instance (used for key validation)
        key: Category key to look up

    Returns:
        Category ID or None if key is invalid or not found
    """
    if not taxonomy.is_valid_key(key):
        return None
    return db.get_category_id_by_key(key)
```

**Size**: ~60 lines

---

## Import Update Cheatsheet

### Search and Replace Commands

Replace these patterns across the codebase:

```bash
# Core taxonomy imports
from services.taxonomy import Taxonomy
  ↓
from src.transactoid.taxonomy.core import Taxonomy

from services.taxonomy import CategoryNode
  ↓
from src.transactoid.taxonomy.core import CategoryNode

# Database imports
from services.db import DB
  ↓
from src.transactoid.infrastructure.db.facade import DB

from services.db import Base, Merchant, Category, Transaction, etc.
  ↓
from src.transactoid.infrastructure.db.models import Base, Merchant, Category, Transaction

# Cache imports
from services.file_cache import FileCache, stable_key
  ↓
from src.transactoid.infrastructure.cache.file_cache import FileCache, stable_key

# Plaid imports
from services.plaid_client import PlaidClient, PlaidClientError
  ↓
from src.transactoid.infrastructure.clients.plaid import PlaidClient, PlaidClientError

from services.plaid_link_flow import (...)
  ↓
from src.transactoid.infrastructure.clients.plaid_link import (...)

# Taxonomy generator imports
from services import taxonomy_generator as tg
  ↓
from src.transactoid.taxonomy import generator as tg

# YAML utils imports
from services.yaml_utils import dump_yaml, dump_yaml_basic
  ↓
from src.transactoid.utils.yaml import dump_yaml, dump_yaml_basic

# NEW: Taxonomy loader imports (for code that loads taxonomy from DB)
from src.transactoid.taxonomy.loader import load_taxonomy_from_db
from src.transactoid.taxonomy.loader import get_category_id
```

### Files to Update (32+ import sites)

**Scripts** (4 files):
- [ ] `scripts/run.py`
- [ ] `scripts/seed_taxonomy.py`
- [ ] `scripts/build_taxonomy.py`
- [ ] `scripts/plaid_cli.py`

**Tools** (4 files):
- [ ] `tools/categorize/categorizer_tool.py`
- [ ] `tools/persist/persist_tool.py`
- [ ] `tools/query/query_tool.py`
- [ ] `tools/sync/sync_tool.py`

**Orchestrators** (1 file):
- [ ] `orchestrators/transactoid.py`

**UI** (3 files):
- [ ] `ui/cli.py`
- [ ] `frontends/chatkit_server.py`
- [ ] `frontends/mcp_server.py`

**Tests** (10+ files):
- [ ] `tests/services/test_db.py`
- [ ] `tests/services/test_taxonomy.py`
- [ ] `tests/services/test_taxonomy_generator.py`
- [ ] `tests/services/test_file_cache.py`
- [ ] `tests/scripts/test_seed_taxonomy.py`
- [ ] `tests/scripts/test_migrate_legacy_categories.py`
- [ ] `tests/tools/persist/test_persist_tool.py`

**Alembic** (1 file):
- [ ] `alembic/env.py`

---

## Files to Create (Directory Structure)

### New Directories
```
src/transactoid/
├── infrastructure/
│   ├── __init__.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py           ← from services/db.py (part 1)
│   │   └── facade.py           ← from services/db.py (part 2, refactored)
│   ├── cache/
│   │   ├── __init__.py
│   │   └── file_cache.py       ← from services/file_cache.py
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── plaid.py            ← from services/plaid_client.py
│   │   └── plaid_link.py       ← from services/plaid_link_flow.py
│   └── [other infrastructure]
│
├── utils/
│   ├── __init__.py
│   └── yaml.py                 ← from services/yaml_utils.py
│
└── taxonomy/
    ├── __init__.py
    ├── core.py                 ← from services/taxonomy.py (part 1)
    ├── loader.py               ← NEW (part 2)
    └── generator.py            ← from services/taxonomy_generator.py
```

### New __init__.py Files to Create
- [ ] `src/transactoid/infrastructure/__init__.py`
- [ ] `src/transactoid/infrastructure/db/__init__.py`
- [ ] `src/transactoid/infrastructure/cache/__init__.py`
- [ ] `src/transactoid/infrastructure/clients/__init__.py`
- [ ] `src/transactoid/utils/__init__.py`
- [ ] `src/transactoid/taxonomy/__init__.py`

---

## Verification Checklist

After migration, verify:

### Import Resolution
```bash
# Should have NO results (all old imports gone)
grep -r "from services\." src/ tests/ scripts/ orchestrators/ ui/ frontends/
grep -r "import services" src/ tests/ scripts/ orchestrators/ ui/ frontends/

# Should have results (new imports in place)
grep -r "from src\.transactoid\.infrastructure" src/ tests/
grep -r "from src\.transactoid\.taxonomy" src/ tests/
```

### No Circular Imports
```bash
# Use Python's import checker
python -m py_compile src/transactoid/infrastructure/db/facade.py  # should succeed
python -m py_compile src/transactoid/taxonomy/core.py            # should succeed
python -m py_compile src/transactoid/taxonomy/loader.py          # should succeed

# No cross-imports between facade.py and core.py
grep "taxonomy" src/transactoid/infrastructure/db/facade.py      # should have ZERO results
grep "db.facade" src/transactoid/taxonomy/core.py              # should have ZERO results
```

### Files Deleted
```bash
# Should NOT exist
ls -la services/                    # should fail
ls -la tests/services/             # should fail
```

### Tests Pass
```bash
uv run pytest tests/ -v
```

### Type Checking
```bash
uv run mypy --config-file mypy.ini src/ tests/
```

---

## Special Cases

### Alembic Migrations

**File**: `alembic/env.py`

**Current**:
```python
from services.db import Base
```

**Update to**:
```python
from src.transactoid.infrastructure.db.models import Base
```

### Models TypedDict

**File**: `src/transactoid/infrastructure/db/models.py`

The `CategoryRow` TypedDict moves with the models:
```python
class CategoryRow(TypedDict):
    category_id: int
    parent_id: int | None
    key: str
    name: str
    description: str | None
    parent_key: str | None
```

This is imported by:
- `loader.py` (for type hints in `load_taxonomy_from_db()`)
- `facade.py` (return type of `fetch_categories()`)

---

## Timeline Estimate

Assuming systematic, tested migration:

1. **Create directory structure**: 10 min
2. **Migrate yaml_utils.py**: 5 min (trivial, no deps)
3. **Migrate db.py (split into 2)**: 30 min (large, refactor save_transactions)
4. **Migrate taxonomy.py (split into 2)**: 20 min (remove imports, create loader)
5. **Migrate other services**: 15 min (plaid, cache, generators — no deps)
6. **Update 32+ import sites**: 60 min (systematic find/replace + verification)
7. **Update tests**: 30 min (same imports as source)
8. **Verify + fix type errors**: 30 min (mypy will catch issues)
9. **Test run**: 10 min (`pytest`, `ruff`, `mypy`, etc.)

**Total**: ~3-4 hours for complete, tested migration.
