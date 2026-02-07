# Circular Dependency Resolution

## The Problem

### Current State (CIRCULAR)

```
services/taxonomy.py
├── imports: from services.db import DB
└── uses: DB.fetch_categories() in Taxonomy.from_db()

services/db.py
├── imports (TYPE_CHECKING): from services.taxonomy import Taxonomy
└── uses: taxonomy.category_id_for_key(self, key) in save_transactions()
```

**Dependency graph:**
```
taxonomy ──→ db
  ↑          ↓
  └──────────┘
```

**Problems this creates:**
1. TYPE_CHECKING import doesn't help at runtime — tests/circular reference tooling can still detect it
2. Hard to understand: which module is responsible for Taxonomy ↔ DB interaction?
3. Tight coupling: DB can't be tested independently of Taxonomy
4. Can't refactor one without affecting the other

---

## The Solution: Three-Module Approach

### New State (CLEAN)

```
src/transactoid/taxonomy/
├── core.py                  (pure domain: Taxonomy, CategoryNode)
├── loader.py               (instantiation: DB ↔ Taxonomy bridge)
└── generator.py            (YAML → Taxonomy)

src/transactoid/infrastructure/db/
├── models.py               (pure schema: ORM models)
└── facade.py               (DB service layer: queries/mutations)
```

**Dependency graph:**
```
taxonomy/core.py ────┐
                     └──→ loader.py
infrastructure/db/facade.py
                     ↑
                     │
loader.py ──────────┘
```

**Key insight**: Loader is the **only place** that knows both.

---

## Before vs. After: Code Examples

### BEFORE: Circular imports

#### services/taxonomy.py
```python
from services.db import DB  # ← IMPORT

class Taxonomy:
    @classmethod
    def from_db(cls, db: DB) -> Taxonomy:
        rows = db.fetch_categories()  # ← USE
        ...

    def category_id_for_key(self, db: DB, key: str) -> int | None:
        return db.get_category_id_by_key(key)  # ← USE
```

#### services/db.py
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.taxonomy import Taxonomy  # ← TYPE_CHECKING IMPORT

class DB:
    def save_transactions(
        self,
        taxonomy: Taxonomy,  # ← USE TYPE
        txns: Iterable[CategorizedTransaction],
    ) -> SaveOutcome:
        ...
        category_id = taxonomy.category_id_for_key(self, category_key)  # ← USE
```

**Problem**: `db.save_transactions()` accepts Taxonomy but doesn't import it (only in TYPE_CHECKING). This creates confusion and fails at runtime if anyone tries to pass the wrong type.

---

### AFTER: Clean separation with loader

#### src/transactoid/taxonomy/core.py
```python
# PURE DOMAIN: NO INFRASTRUCTURE IMPORTS
from dataclasses import dataclass
from collections.abc import Sequence

@dataclass(frozen=True)
class CategoryNode:
    key: str
    name: str
    description: str | None
    parent_key: str | None

class Taxonomy:
    def __init__(self, nodes: Sequence[CategoryNode]) -> None:
        self._nodes_by_key: dict[str, CategoryNode] = {n.key: n for n in nodes}
        # ... build tree structure ...

    @classmethod
    def from_nodes(cls, nodes: Sequence[CategoryNode]) -> Taxonomy:
        """Build from pre-loaded nodes (dependency injection)."""
        return cls(sorted(nodes, key=lambda n: n.key))

    def is_valid_key(self, key: str) -> bool:
        return key in self._nodes_by_key

    def get(self, key: str) -> CategoryNode | None:
        return self._nodes_by_key.get(key)

    def children(self, key: str) -> list[CategoryNode]:
        return list(self._children.get(key, []))

    def to_prompt(self, include_keys: Iterable[str] | None = None) -> dict[str, object]:
        # ... format for LLM ...
```

**Key change**: `from_db()` removed. Taxonomy only builds from nodes — caller's responsibility to load nodes from DB.

---

#### src/transactoid/taxonomy/loader.py (NEW)
```python
# ORCHESTRATION: IMPORTS BOTH TAXONOMY AND DB
from src.transactoid.taxonomy.core import Taxonomy, CategoryNode
from src.transactoid.infrastructure.db.facade import DB

def load_taxonomy_from_db(db: DB) -> Taxonomy:
    """Load taxonomy from database.

    Single point of responsibility for DB ↔ Taxonomy interaction.
    Neither Taxonomy nor DB need to know about each other.
    """
    rows = db.fetch_categories()
    nodes = [
        CategoryNode(
            key=row["key"],
            name=row["name"],
            description=row.get("description"),
            parent_key=row.get("parent_key"),
        )
        for row in rows
    ]
    return Taxonomy.from_nodes(nodes)


def get_category_id(db: DB, taxonomy: Taxonomy, key: str) -> int | None:
    """Look up category ID using taxonomy and DB together.

    This replaces Taxonomy.category_id_for_key(self, db).
    Now it's clear: you need both Taxonomy AND DB to look up category IDs.
    """
    if not taxonomy.is_valid_key(key):
        return None
    return db.get_category_id_by_key(key)
```

**Key insight**: The loader module is the **contract** — it says "to use Taxonomy with DB, go through loader functions."

---

#### src/transactoid/infrastructure/db/facade.py
```python
# INFRASTRUCTURE: KNOWS NOTHING ABOUT TAXONOMY

from typing import Callable, Iterable, Any
from src.transactoid.infrastructure.db.models import Transaction, Category, Merchant
from sqlalchemy.orm import Session

class DB:
    def __init__(self, url: str) -> None:
        # ... setup engine, sessions ...

    def get_category_id_by_key(self, key: str) -> int | None:
        """Lookup category by key. Caller handles validation."""
        with self.session() as session:
            category = session.query(Category).filter(Category.key == key).first()
            return category.category_id if category else None

    def save_transactions(
        self,
        category_lookup: Callable[[str], int | None],  # ← INJECTED CALLBACK
        txns: Iterable[CategorizedTransaction],
    ) -> SaveOutcome:
        """Save categorized transactions.

        Uses injected category_lookup callback instead of Taxonomy object.
        DB doesn't care HOW the lookup works — just calls the callback.
        """
        for cat_txn in txns:
            category_id = category_lookup(category_key)  # ← INJECT, DON'T KNOW TYPE
            # ... rest of save logic ...

    def fetch_categories(self) -> list[CategoryRow]:
        """Fetch all categories as dicts. Caller handles instantiation."""
        with self.session() as session:
            categories = session.query(Category).all()
            # ... map to CategoryRow dicts ...
            return rows
```

**Key change**: `save_transactions()` now takes a callback, not a Taxonomy object. DB doesn't import Taxonomy.

---

## Usage: How Callers Interact

### Before: Direct from services
```python
# ui/cli.py
from services.db import DB
from services.taxonomy import Taxonomy

db = DB(database_url)
taxonomy = Taxonomy.from_db(db)  # ← confusing: Taxonomy calls into DB
```

### After: Via loader
```python
# ui/cli.py
from src.transactoid.infrastructure.db.facade import DB
from src.transactoid.taxonomy.loader import load_taxonomy_from_db

db = DB(database_url)
taxonomy = load_taxonomy_from_db(db)  # ← clear: loader does the loading
```

### Before: Saving with Taxonomy
```python
# tools/persist/persist_tool.py
from services.db import DB
from services.taxonomy import Taxonomy

def persist_transactions(db: DB, taxonomy: Taxonomy, txns):
    outcome = db.save_transactions(taxonomy, txns)  # ← Taxonomy passed as object
```

### After: Saving with callback
```python
# tools/persist/persist_tool.py
from src.transactoid.infrastructure.db.facade import DB
from src.transactoid.taxonomy.core import Taxonomy
from src.transactoid.taxonomy.loader import get_category_id

def persist_transactions(db: DB, taxonomy: Taxonomy, txns):
    # Create a lookup function that uses both
    category_lookup = lambda key: get_category_id(db, taxonomy, key)
    outcome = db.save_transactions(category_lookup, txns)  # ← Callback injected
```

---

## Import Analysis: Why This Works

### Current Cyclic Imports (BAD)
```
services/taxonomy.py
  ├── import DB from services/db.py      ← IMPORT AT MODULE LEVEL
  └── uses it in classmethod

services/db.py
  ├── from typing import TYPE_CHECKING
  └── if TYPE_CHECKING:
      └── from services/taxonomy import Taxonomy  ← ONLY IMPORT FOR TYPES

Problem: Mixing TYPE_CHECKING with runtime usage creates confusion
```

### New Clean Imports (GOOD)
```
src/transactoid/taxonomy/core.py
  ├── imports: dataclasses, collections.abc
  ├── NO infrastructure imports
  └── can be imported by DB without risk

src/transactoid/taxonomy/loader.py
  ├── imports: taxonomy.core, infrastructure.db.facade
  └── responsible for connecting the two

src/transactoid/infrastructure/db/facade.py
  ├── imports: infrastructure.db.models, sqlalchemy, typing
  ├── NO taxonomy imports
  └── uses injected callbacks for domain logic

Callers:
  ├── import loader + db + taxonomy
  └── use loader to instantiate, then pass callback to db
```

**Why no cycles?**
- core.py: only imports stdlib + domain types → nothing can import core and create cycle
- facade.py: only imports models + stdlib → only infra can import it
- loader.py: imports both, but neither imports loader → no cycle (loader is leaf)

---

## Tests: How They Change

### Before: Testing Taxonomy + DB coupling
```python
# tests/services/test_taxonomy.py
from services.db import DB  # must import DB just to test Taxonomy
from services.taxonomy import Taxonomy

def test_taxonomy_from_db():
    db = DB(":memory:")  # must instantiate DB for Taxonomy
    db.setup_schema()
    # ... insert test data ...
    taxonomy = Taxonomy.from_db(db)  # ← Taxonomy directly calls DB
    assert taxonomy.is_valid_key("housing")
```

### After: Testing Taxonomy independently
```python
# tests/taxonomy/test_core.py
from src.transactoid.taxonomy.core import Taxonomy, CategoryNode

def test_taxonomy_from_nodes():
    nodes = [
        CategoryNode(key="housing", name="Housing", description=None, parent_key=None),
        CategoryNode(key="rent", name="Rent", description=None, parent_key="housing"),
    ]
    taxonomy = Taxonomy.from_nodes(nodes)
    assert taxonomy.is_valid_key("housing")
    assert taxonomy.is_valid_key("rent")
```

**Benefit**: Taxonomy tests don't need DB setup; much faster and simpler.

```python
# tests/taxonomy/test_loader.py
from src.transactoid.taxonomy.loader import load_taxonomy_from_db
from src.transactoid.infrastructure.db.facade import DB

def test_load_taxonomy_from_db():
    db = DB(":memory:")
    db.setup_schema()
    # ... insert categories ...
    taxonomy = load_taxonomy_from_db(db)  # ← Clear: loader handles DB interaction
    assert taxonomy.is_valid_key("housing")
```

---

## Performance: No Change

The refactoring is structural; runtime behavior is identical:
- Same database queries (just called differently)
- Same Taxonomy instantiation (just from different place)
- Same callback invocation in save_transactions (instead of method call)

**Potential benefit**: Dependency injection makes it easier to add caching or mocking later.

---

## Summary Table

| Aspect | Before | After |
|--------|--------|-------|
| Taxonomy import | `from services.db import DB` | None (pure domain) |
| DB import | `if TYPE_CHECKING: Taxonomy` | None (pure infra) |
| Loading Taxonomy | `Taxonomy.from_db(db)` | `load_taxonomy_from_db(db)` |
| Category lookup | `taxonomy.category_id_for_key(db, key)` | `get_category_id(db, taxonomy, key)` |
| Saving txns | `db.save_transactions(taxonomy, txns)` | `db.save_transactions(category_lookup, txns)` |
| Testing Taxonomy | Need DB setup | Just nodes (no DB) |
| Circular imports | YES (TYPE_CHECKING) | NO |
| Clear responsibility | NO (mixed) | YES (loader owns bridge) |
