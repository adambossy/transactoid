# Services Layer Migration Plan (Detailed)

## Executive Summary

The `services/` directory contains 9 files mixing infrastructure, domain logic, and third-party integrations. This plan maps each file to its new home in `src/transactoid/`, with special attention to **breaking the Taxonomy ↔ DB circular dependency**.

**Key Change**: The circular reference is eliminated by:
1. Moving Taxonomy domain logic → `src/transactoid/taxonomy/core.py` (pure domain)
2. Splitting DB layer → `src/transactoid/infrastructure/db/models.py` + `src/transactoid/infrastructure/db/facade.py`
3. Creating a **loader module** → `src/transactoid/taxonomy/loader.py` that owns the DB-to-Taxonomy instantiation
4. Inverting Taxonomy usage in DB: inject category lookup callbacks instead of passing Taxonomy objects

---

## File-by-File Migration Map

### 1. `services/db.py` (1000+ lines) → **SPLIT INTO 2 FILES**

**Problem**: This file contains:
- SQLAlchemy ORM models (Merchant, Category, Transaction, Tag, PlaidItem) — pure schema
- DB service layer (class DB with 20+ methods) — business logic
- Circular imports: imports Taxonomy in TYPE_CHECKING; used in `save_transactions()`

**Solution**: Split cleanly to separate concerns.

#### 1a. `services/db.py` → `src/transactoid/infrastructure/db/models.py` (Schema only)

**What goes here**: All SQLAlchemy models (pure schema, zero business logic)
```python
class Base(DeclarativeBase): ...
class Merchant(Base): ...
class Category(Base): ...
class Transaction(Base): ...
class Tag(Base): ...
class TransactionTag(Base): ...
class PlaidItem(Base): ...
```

**What imports it needs**:
```python
from sqlalchemy import (TIMESTAMP, Boolean, Date, ForeignKey, Integer, String, Text, 
                        UniqueConstraint, case, create_engine, text)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column, 
                            relationship, sessionmaker)
```

**Zero business logic imports** ✓ (no services, no taxonomy, no tools)

---

#### 1b. `services/db.py` → `src/transactoid/infrastructure/db/facade.py` (DB service layer)

**What goes here**: DB class with all query/mutation methods (minus taxonomy dependencies)

**Key methods**:
- `__init__`, `session()`, `execute_raw_sql()`, `run_sql()`
- `fetch_transactions_by_ids_preserving_order()`
- `get_category_id_by_key()` — **KEY: keeps this, but changes signature**
- `find_merchant_by_normalized_name()`
- `create_merchant()`, `insert_transaction()`, `update_transaction_mutable()`
- `upsert_tag()`, `attach_tags()`, `delete_transactions_by_external_ids()`
- `recategorize_unverified_by_merchant()`
- `save_transactions()` — **REFACTORED** (see below)
- `compact_schema_hint()`, `fetch_categories()`, `replace_categories_rows()`
- `save_plaid_item()`, `get_plaid_item()`, `list_plaid_items()`

**Imports**:
```python
from src.transactoid.infrastructure.db.models import (
    Base, Merchant, Category, Transaction, Tag, TransactionTag, PlaidItem
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from typing import TypedDict, Any, cast
```

**NO imports from taxonomy** ✓

**Critical change to `save_transactions()` method**:

**Before** (circular):
```python
def save_transactions(
    self,
    taxonomy: Taxonomy,  # ← circular import
    txns: Iterable[CategorizedTransaction],
) -> SaveOutcome:
    for cat_txn in txns:
        category_id = taxonomy.category_id_for_key(self, category_key)  # ← calls back to Taxonomy
        ...
```

**After** (refactored, no Taxonomy import):
```python
def save_transactions(
    self,
    category_lookup: Callable[[str], int | None],  # ← injected callback
    txns: Iterable[CategorizedTransaction],
) -> SaveOutcome:
    for cat_txn in txns:
        category_id = category_lookup(category_key)  # ← uses injected function
        ...
```

**Benefit**: DB doesn't know about Taxonomy; caller handles the lookup.

---

### 2. `services/taxonomy.py` (120 lines) → `src/transactoid/taxonomy/core.py`

**What goes here**: Taxonomy and CategoryNode classes (pure domain logic)

```python
@dataclass(frozen=True)
class CategoryNode:
    key: str
    name: str
    description: str | None
    parent_key: str | None

class Taxonomy:
    def __init__(self, nodes: Sequence[CategoryNode]) -> None: ...
    @classmethod
    def from_nodes(cls, nodes: Sequence[CategoryNode]) -> Taxonomy: ...
    def is_valid_key(self, key: str) -> bool: ...
    def get(self, key: str) -> CategoryNode | None: ...
    def children(self, key: str) -> list[CategoryNode]: ...
    def parent(self, key: str) -> CategoryNode | None: ...
    def parents(self) -> list[CategoryNode]: ...
    def all_nodes(self) -> list[CategoryNode]: ...
    def to_prompt(self, include_keys: Iterable[str] | None = None) -> dict[str, object]: ...
    def path_str(self, key: str, sep: str = " > ") -> str | None: ...
```

**Remove from this file**:
- `@classmethod from_db()` — move to `src/transactoid/taxonomy/loader.py`
- `def category_id_for_key(self, db: DB, key: str)` — move to `src/transactoid/infrastructure/db/facade.py`

**Result**: Pure domain object, zero infrastructure imports ✓

---

### 3. `services/taxonomy.py` → NEW: `src/transactoid/taxonomy/loader.py`

**New file**: Owns the responsibility of instantiating Taxonomy from DB.

```python
"""Taxonomy loader: instantiates Taxonomy from database or nodes."""

from src.transactoid.infrastructure.db.facade import DB
from src.transactoid.infrastructure.db.models import CategoryRow
from src.transactoid.taxonomy.core import Taxonomy, CategoryNode

def load_taxonomy_from_db(db: DB) -> Taxonomy:
    """Load taxonomy from database.
    
    Args:
        db: Database facade instance
        
    Returns:
        Constructed Taxonomy object
    """
    rows = db.fetch_categories()
    nodes = [
        CategoryNode(
            key=str(row["key"]),
            name=str(row["name"]),
            description=(
                None if row.get("description") is None 
                else str(row["description"])
            ),
            parent_key=(
                None if row.get("parent_key") is None 
                else str(row["parent_key"])
            ),
        )
        for row in rows
    ]
    # Sort to keep stable order
    nodes_sorted = sorted(nodes, key=lambda n: n.key)
    return Taxonomy.from_nodes(nodes_sorted)


def get_category_id(db: DB, taxonomy: Taxonomy, key: str) -> int | None:
    """Look up category ID from DB using key.
    
    This is the inverse of DB's get_category_id_by_key():
    - DB knows how to fetch by key
    - This function knows how to use Taxonomy + DB together
    
    Args:
        db: Database facade
        taxonomy: Taxonomy instance (unused directly, but validates key)
        key: Category key to look up
        
    Returns:
        Category ID or None if not found
    """
    if not taxonomy.is_valid_key(key):
        return None
    return db.get_category_id_by_key(key)
```

**Benefit**: Single place where Taxonomy and DB interact; both import this module, but not each other.

---

### 4. `services/taxonomy_generator.py` → `src/transactoid/taxonomy/generator.py`

**What goes here**: Entire file (YAML → Taxonomy instantiation)

**Changes**:
- Update import: `from services.yaml_utils import dump_yaml` → `from src.transactoid.utils.yaml import dump_yaml`

**No structural changes needed** ✓

---

### 5. `services/plaid_client.py` → `src/transactoid/infrastructure/clients/plaid.py`

**What goes here**: Entire PlaidClient class and all Plaid-specific types

**Update imports**:
```python
# Before:
from models.transaction import PersonalFinanceCategory, Transaction
from services.plaid_link_flow import (...)

# After:
from src.transactoid.models.transaction import PersonalFinanceCategory, Transaction
from src.transactoid.infrastructure.clients.plaid_link import (...)
```

**No structural changes** ✓

---

### 6. `services/plaid_link_flow.py` → `src/transactoid/infrastructure/clients/plaid_link.py`

**What goes here**: Entire plaid_link_flow module (OAuth redirect server)

**No imports from services** ✓

---

### 7. `services/file_cache.py` → `src/transactoid/infrastructure/cache/file_cache.py`

**What goes here**: Entire FileCache class

**No imports from other services** ✓

---

### 8. `services/yaml_utils.py` → `src/transactoid/utils/yaml.py`

**What goes here**: dump_yaml(), dump_yaml_basic() functions

**No imports from services** ✓

**Note**: This is a **utility**, not infrastructure, so it goes in `utils/` not `infrastructure/`

---

### 9. `services/__init__.py` → Delete or make minimal

**Current**: Likely empty or has `__all__`

**New approach**: Each module is imported directly:
- `from src.transactoid.taxonomy.core import Taxonomy`
- `from src.transactoid.infrastructure.db.facade import DB`
- etc.

No aggregating `__init__.py` needed.

---

## Dependency Graph (After Migration)

```
src/transactoid/
├── models/transaction.py           → (nothing)
│   ├── Transaction (TypedDict)
│   └── PersonalFinanceCategory (TypedDict)
│   
├── core/
│   └── errors.py                   → models/
│
├── taxonomy/
│   ├── core.py                     → models/, core/errors
│   │   └── Taxonomy, CategoryNode
│   ├── loader.py                   → core.py, infrastructure/db/facade
│   ├── generator.py                → core.py, utils/yaml
│   └── errors.py                   → (nothing or core/errors)
│
├── infrastructure/
│   ├── db/
│   │   ├── models.py               → (sqlalchemy only)
│   │   │   └── Base, Merchant, Category, Transaction, Tag, etc.
│   │   └── facade.py               → models.py
│   │       └── DB class (all queries/mutations)
│   ├── cache/
│   │   └── file_cache.py           → (logging, pathlib, json)
│   │       └── FileCache class
│   ├── clients/
│   │   ├── plaid.py                → models/transaction, plaid_link
│   │   │   └── PlaidClient
│   │   └── plaid_link.py           → (http.server, ssl, etc.)
│   │       └── OAuth flow functions
│   └── [future integrations]
│
└── utils/
    └── yaml.py                      → (yaml library)
        └── dump_yaml(), dump_yaml_basic()
```

**Key invariants**:
```
models/            → (nothing)
  ↑
├── core/          → models/
├── taxonomy/      → models/, core/
│   └── loader.py  → infrastructure/db/
│
└── infrastructure/ → models/, core/, taxonomy/
    ├── db/facade → only imports db/models, not taxonomy
    ├── clients/
    └── cache/
```

**No circular imports** ✓

---

## Updated Call Sites

### Before: `save_transactions()` in tools/persist/persist_tool.py

```python
from services.db import DB
from services.taxonomy import Taxonomy

def save_transactions(db: DB, taxonomy: Taxonomy, txns: Iterable[CategorizedTransaction]):
    outcome = db.save_transactions(taxonomy, txns)
    return outcome
```

### After: Using refactored interface

```python
from src.transactoid.infrastructure.db.facade import DB
from src.transactoid.taxonomy.core import Taxonomy
from src.transactoid.taxonomy.loader import get_category_id

def save_transactions(db: DB, taxonomy: Taxonomy, txns: Iterable[CategorizedTransaction]):
    # Create a lookup callback
    category_lookup = lambda key: get_category_id(db, taxonomy, key)
    outcome = db.save_transactions(category_lookup, txns)
    return outcome
```

### Before: Loading taxonomy in ui/cli.py

```python
from services.db import DB
from services.taxonomy import Taxonomy

db = DB(database_url)
taxonomy = Taxonomy.from_db(db)
```

### After: Using loader module

```python
from src.transactoid.infrastructure.db.facade import DB
from src.transactoid.taxonomy.loader import load_taxonomy_from_db

db = DB(database_url)
taxonomy = load_taxonomy_from_db(db)
```

---

## Migration Checklist

### Phase 1: Create new directory structure
- [ ] Create `src/transactoid/infrastructure/` directory
- [ ] Create `src/transactoid/infrastructure/db/` directory
- [ ] Create `src/transactoid/infrastructure/cache/` directory
- [ ] Create `src/transactoid/infrastructure/clients/` directory
- [ ] Create `src/transactoid/utils/` directory
- [ ] Create `src/transactoid/taxonomy/` directory (if not exists)

### Phase 2: Migrate files (in order)

**Order matters**: Start with leaves, work toward circular dependency.

1. [ ] Migrate `services/yaml_utils.py` → `src/transactoid/utils/yaml.py`
2. [ ] Migrate `services/db.py` → **SPLIT**:
   - [ ] ORM models → `src/transactoid/infrastructure/db/models.py`
   - [ ] DB class → `src/transactoid/infrastructure/db/facade.py` (refactored to remove taxonomy import)
3. [ ] Migrate `services/taxonomy.py` → `src/transactoid/taxonomy/core.py` (remove `from_db`, `category_id_for_key`)
4. [ ] Create `src/transactoid/taxonomy/loader.py` (new loader module)
5. [ ] Migrate `services/taxonomy_generator.py` → `src/transactoid/taxonomy/generator.py`
6. [ ] Migrate `services/file_cache.py` → `src/transactoid/infrastructure/cache/file_cache.py`
7. [ ] Migrate `services/plaid_link_flow.py` → `src/transactoid/infrastructure/clients/plaid_link.py`
8. [ ] Migrate `services/plaid_client.py` → `src/transactoid/infrastructure/clients/plaid.py`

### Phase 3: Update all imports (32+ files)

Update imports in these locations:
- [ ] `scripts/*.py` (4 files)
- [ ] `tools/**/*.py` (3+ files)
- [ ] `orchestrators/*.py` (1 file)
- [ ] `ui/*.py` (1 file)
- [ ] `frontends/*.py` (2 files) — **Also part of UI consolidation**
- [ ] `adapters/*.py` (3 files) — **Also part of UI consolidation**
- [ ] `tests/**/*.py` (10+ files)

**Import replacements** (sed-friendly):
```
services.db → src.transactoid.infrastructure.db.facade
services.taxonomy → src.transactoid.taxonomy.core
services.file_cache → src.transactoid.infrastructure.cache.file_cache
services.plaid_client → src.transactoid.infrastructure.clients.plaid
services.plaid_link_flow → src.transactoid.infrastructure.clients.plaid_link
services.yaml_utils → src.transactoid.utils.yaml
services.taxonomy_generator → src.transactoid.taxonomy.generator
```

### Phase 4: Add __init__.py files

- [ ] `src/transactoid/infrastructure/__init__.py`
- [ ] `src/transactoid/infrastructure/db/__init__.py`
- [ ] `src/transactoid/infrastructure/cache/__init__.py`
- [ ] `src/transactoid/infrastructure/clients/__init__.py`
- [ ] `src/transactoid/utils/__init__.py`
- [ ] `src/transactoid/taxonomy/__init__.py` (may already exist)

### Phase 5: Update pyproject.toml

```toml
[project.scripts]
transactoid = "transactoid.ui.cli:agent"

[tool.setuptools.packages.find]
include = ["src/transactoid", "models"]
```

### Phase 6: Verify & test

- [ ] Run linter: `uv run ruff check .`
- [ ] Run formatter: `uv run ruff format .`
- [ ] Run type-checker: `uv run mypy --config-file mypy.ini .`
- [ ] Run dead code: `uv run deadcode .`
- [ ] Run tests: `uv run pytest -q`

### Phase 7: Delete old files

- [ ] Delete `services/` directory (entire tree)
- [ ] Delete `tests/services/` directory

---

## Key Design Decisions

### 1. Why split `db.py`?

Models and service layer have different stability and reuse patterns:
- Models are stable schema; imported everywhere
- Service layer is business logic; imported by tools/orchestrators
- Splitting keeps schema concerns separate from query concerns

### 2. Why create `loader.py`?

Breaking the Taxonomy ↔ DB circular dependency requires a **third module** that both can import without circular risk:
- Taxonomy doesn't import DB
- DB doesn't import Taxonomy
- Loader imports both and owns their interaction point

This is a proven pattern for breaking circular dependencies in clean architecture.

### 3. Why inject category_lookup callback?

Instead of passing Taxonomy to `save_transactions()`, we inject a callback:
- Decouples DB from Taxonomy implementation
- Allows different lookup strategies (cache, direct DB query, etc.)
- Reduces method signature bloat if more lookups are needed later

### 4. Why is yaml_utils in utils/, not infrastructure/?

YAML utils are pure utility functions with no infrastructure dependencies:
- No file I/O side effects (just serialization)
- Usable from domain logic, not just infra
- Follows "utils are closer to core than infrastructure" principle

---

## Notes

- **No duplicate types**: `models/transaction.py` stays at root with zero dependencies
- **Single source of truth**: `Taxonomy` defined once in `src/transactoid/taxonomy/core.py`
- **Import consistency**: Package name stays `transactoid` (moving to `src/` is transparent after pyproject.toml update)
- **Alembic migrations**: Update import in `alembic/env.py` to use new DB path
- **Circular imports resolved**: No TYPE_CHECKING tricks needed; clear one-directional flow

