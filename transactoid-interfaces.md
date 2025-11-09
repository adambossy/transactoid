Here’s your **final, consolidated project overview**—directory tree + the **public interfaces and types** for every file, plus each file’s **key dependencies**. Everything reflects the revisions we made along the way (e.g., two-level taxonomy; `category_key` → `key`; `merchant_descriptor`; Promptorium prompts; single-pass categorization with optional `revised_*`; model-only DB returns; verifier LLM is *not* in DB).

---

# Directory tree (final)

```
transactoid/
├─ agents/
│  ├─ categorizer.py
│  └─ analyzer_tool.py
├─ tools/
│  ├─ ingest/
│  │  ├─ ingest_tool.py
│  │  ├─ csv.py
│  │  └─ plaid.py
│  ├─ categorize/
│  │  └─ categorizer_tool.py
│  ├─ persist/
│  │  └─ persist_tool.py
│  └─ analytics/
│     └─ analytics_tool.py
├─ services/
│  ├─ file_cache.py
│  ├─ plaid_client.py
│  ├─ taxonomy.py
│  └─ db.py
├─ db/
│  ├─ schema.sql
│  └─ migrations/
├─ prompts/
│  ├─ categorize_prompt.md
│  └─ nl_to_sql_prompt.md
├─ ui/
│  └─ cli.py
├─ configs/
│  ├─ config.example.yaml
│  └─ logging.yaml
├─ scripts/
│  ├─ seed_taxonomy.py
│  └─ run.py
├─ tests/
│  └─ ...
├─ .env.example
├─ pyproject.toml
└─ README.md
```

---

# File-by-file interfaces & dependencies

## agents/categorizer.py

**Role:** Orchestrate ingest → categorize → persist. (Handoff is controlled by scripts/CLI.)

```python
from __future__ import annotations
from typing import Iterable, Optional

def run(
    *,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
) -> None:
    """
    Loop:
      - Ingest tool fetches up to batch_size NormalizedTransaction
      - Categorizer.categorize([...]) -> List[CategorizedTransaction]
      - PersistTool.save_transactions([...])
    Stops when ingestion returns an empty batch.
    """
    ...
```

**Depends on:**

* `tools.ingest.ingest_tool.NormalizedTransaction` (data shape)
* `tools.categorize.categorizer_tool.Categorizer`
* `tools.persist.persist_tool.PersistTool`
* `services.taxonomy.Taxonomy` (injected into categorizer)
* Promptorium (prompt key: **`categorize-transacations`**)

---

## agents/analyzer_tool.py

**Role:** NL→SQL QA tool. Public **`verify_sql`** and **`answer`**.

```python
from __future__ import annotations
from typing import Any, Callable, Generic, List, Optional, Type, TypeVar, TypedDict
from sqlalchemy.engine import Row
from services.db import Transaction  # ORM sample model

A = TypeVar("A")            # aggregate view-model type
S = TypeVar("S", bound=Transaction)

class AnalyzerSQLRefused(Exception): ...

class AnalyzerAnswer(TypedDict, Generic[A, S]):
    aggregates: List[A]     # caller-provided view-model via row factory
    samples: List[S]        # ORM entities (default: Transaction)
    rationales: List[str]   # optional verifier/model reasons

class AnalyzerTool(Generic[A, S]):
    def __init__(
        self,
        *,
        model_name: str = "gpt-5",
        prompt_key_verify: str = "verify-sql",
        prompt_key_nl2sql: str = "nl-to-sql",
    ) -> None: ...

    def verify_sql(
        self,
        sql: str,
        *,
        rationale_out: Optional[List[str]] = None,
    ) -> None:
        """LLM second opinion on a SQL string; raises AnalyzerSQLRefused on rejection."""
        ...

    def answer(
        self,
        question: str,
        *,
        aggregate_model: Type[A],
        aggregate_row_factory: Callable[[Row[Any]], A],
        sample_model: Type[S] = Transaction,
        sample_pk_column: str = "transaction_id",
        rationale_out: Optional[List[str]] = None,
    ) -> AnalyzerAnswer[A, S]:
        """
        1) Promptorium(prompt_key_nl2sql) + Responses API → {aggregate_sql, sample_rows_sql}
        2) verify_sql(...) on both
        3) DB.run_sql(aggregate_sql, model=aggregate_model, pk_column=...)  [if ORM aggregates]
           OR DB.run_sql with projection via row factory (via caller in scripts)
        4) DB.run_sql(sample_rows_sql, model=sample_model, pk_column=sample_pk_column)
        """
        ...
```

**Depends on:**

* Promptorium prompt keys: **`nl-to-sql`**, **`verify-sql`**
* `services.db.DB.run_sql` (execution; DB does **not** verify SQL)

---

## tools/ingest/ingest_tool.py

**Role:** Shared data shape + provider protocol.

```python
from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol, Literal

Source = Literal["CSV", "PLAID"]

@dataclass
class NormalizedTransaction:
    external_id: Optional[str]      # native id or canonical hash
    account_id: str
    posted_at: date
    amount_cents: int
    currency: str
    merchant_descriptor: str
    source: Source                  # "CSV" | "PLAID"
    source_file: Optional[str] = None
    institution: str = ""           # "Amex" | "Chase" | "Morgan Stanley" | ...

class IngestTool(Protocol):
    def fetch_next_batch(self, batch_size: int) -> list[NormalizedTransaction]: ...
```

**Depends on:**

* `services.db.DB` (implementation may filter out verified in future—opaque here)

---

## tools/ingest/csv.py

**Role:** Recursively walk a CSV directory and yield normalized transactions.

```python
from typing import List
from .ingest_tool import IngestTool, NormalizedTransaction

class CSVIngest(IngestTool):
    def __init__(self, data_dir: str) -> None: ...
    def fetch_next_batch(self, batch_size: int) -> List[NormalizedTransaction]: ...
```

**Depends on:**

* Infers `institution` from filename/header heuristics
* Canonical `external_id` if missing (deterministic hash of stable fields)

---

## tools/ingest/plaid.py

**Role:** Pull transactions from Plaid.

```python
from typing import List, Optional
from datetime import date
from .ingest_tool import IngestTool, NormalizedTransaction

class PlaidIngest(IngestTool):
    def __init__(
        self,
        plaid_client: "PlaidClient",
        *,
        account_ids: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> None: ...

    def fetch_next_batch(self, batch_size: int) -> List[NormalizedTransaction]: ...
```

**Depends on:**

* `services.plaid_client.PlaidClient`
* Canonical `external_id` if missing (same rule as CSV)

---

## tools/categorize/categorizer_tool.py

**Role:** Single concrete categorizer; **batch-only** API; single-pass (model may include `revised_*` in same response).

```python
from dataclasses import dataclass
from typing import Iterable, Optional, List
from tools.ingest.ingest_tool import NormalizedTransaction

@dataclass
class CategorizedTransaction:
    txn: NormalizedTransaction
    category_key: str
    category_confidence: float
    category_rationale: str
    revised_category_key: Optional[str] = None
    revised_category_confidence: Optional[float] = None
    revised_category_rationale: Optional[str] = None

class Categorizer:
    def __init__(
        self,
        taxonomy: "Taxonomy",
        *,
        prompt_key: str = "categorize-transacations",
        model: str = "gpt-5",
        confidence_threshold: float = 0.70,
    ) -> None: ...

    def categorize(self, txns: Iterable[NormalizedTransaction]) -> List[CategorizedTransaction]: ...
```

**Depends on:**

* Promptorium key: **`categorize-transacations`** (single pass)
* `services.taxonomy.Taxonomy.is_valid_key` (parents + children; no fallback key)

---

## tools/persist/persist_tool.py

**Role:** Upsert with dedupe; enforce immutability; tagging; bulk recategorization by merchant.

```python
from dataclasses import dataclass
from typing import Iterable, List
from tools.categorize.categorizer_tool import CategorizedTransaction

@dataclass
class SaveRowOutcome:
    external_id: str
    source: str                      # "CSV" | "PLAID"
    action: str                      # "inserted" | "updated" | "skipped-verified" | "skipped-duplicate"
    transaction_id: int | None = None
    reason: str | None = None

@dataclass
class SaveOutcome:
    inserted: int
    updated: int
    skipped_verified: int
    skipped_duplicate: int
    rows: List[SaveRowOutcome]

@dataclass
class ApplyTagsOutcome:
    applied: int
    created_tags: List[str]

class PersistTool:
    def __init__(self, db: "DB", taxonomy: "Taxonomy") -> None: ...

    def save_transactions(self, txns: Iterable[CategorizedTransaction]) -> SaveOutcome: ...
    def bulk_recategorize_by_merchant(self, merchant_id: int, category_key: str, *, only_unverified: bool = True) -> int: ...
    def apply_tags(self, transaction_ids: list[int], tag_names: list[str]) -> ApplyTagsOutcome: ...
```

**Depends on:**

* `services.db.DB` (ORM ops)
* `services.taxonomy.Taxonomy` (validate key, map to `category_id`)

---

## tools/analytics/analytics_tool.py

**Role:** **Verifier-only** helper; *no execution here*. (DB handles execution and returns model objects.)

```python
from typing import Optional, List, Type, TypeVar
from services.db import DB

M = TypeVar("M")

class AnalyticsSQLRefused(Exception): ...

class AnalyticsTool:
    def __init__(
        self,
        db: DB,
        *,
        model: Type[M],
        prompt_key_verify: str = "verify-sql",
        max_rows: Optional[int] = None,
    ) -> None: ...

    def _verify_sql(
        self,
        sql: str,
        *,
        rationale_out: Optional[List[str]] = None,
    ) -> None:
        """LLM-based second opinion; raises AnalyticsSQLRefused on rejection."""
        ...

    def _load_verify_prompt(self) -> str: ...
    def _schema_hint(self) -> dict: ...
```

**Depends on:**

* Promptorium key: **`verify-sql`**
* `services.db.DB.compact_schema_hint` (internal prompt context)

---

## services/file_cache.py

**Role:** Namespaced JSON file cache; stable keys.

```python
from typing import Any, Dict, List, Optional

JSONType = Any

class FileCache:
    def __init__(self, base_dir: str = ".cache") -> None: ...
    def get(self, namespace: str, key: str) -> Optional[JSONType]: ...
    def set(self, namespace: str, key: str, value: JSONType) -> None: ...
    def exists(self, namespace: str, key: str) -> bool: ...
    def delete(self, namespace: str, key: str) -> bool: ...
    def clear_namespace(self, namespace: str) -> int: ...
    def list_keys(self, namespace: str) -> List[str]: ...
    def path_for(self, namespace: str, key: str) -> str: ...
    def _atomic_writer(self, namespace: str, key: str): ...
def stable_key(payload: Any) -> str: ...
```

**Depends on:**

* None (local FS only). Used implicitly by LLM call sites for caching.

---

## services/plaid_client.py

**Role:** Minimal Plaid wrapper.

```python
from typing import Any, Dict, List, Literal, Optional, TypedDict
from datetime import date

PlaidEnv = Literal["sandbox", "development", "production"]

class PlaidAccount(TypedDict):
    account_id: str
    name: str
    official_name: Optional[str]
    mask: Optional[str]
    subtype: Optional[str]
    type: Optional[str]
    institution: Optional[str]

class PlaidTransaction(TypedDict):
    transaction_id: Optional[str]
    account_id: str
    amount: float
    iso_currency_code: Optional[str]
    date: str
    name: str
    merchant_name: Optional[str]
    pending: bool
    payment_channel: Optional[str]
    unofficial_currency_code: Optional[str]

class PlaidItemInfo(TypedDict):
    item_id: str
    institution_id: Optional[str]
    institution_name: Optional[str]

class PlaidClient:
    def __init__(self, *, client_id: str, secret: str, env: PlaidEnv = "sandbox", client_name: str = "transactoid", products: Optional[List[str]] = None) -> None: ...
    def create_link_token(self, *, user_id: str, redirect_uri: Optional[str] = None) -> str: ...
    def exchange_public_token(self, public_token: str) -> Dict[str, str]: ...
    def get_accounts(self, access_token: str) -> List[PlaidAccount]: ...
    def get_item_info(self, access_token: str) -> PlaidItemInfo: ...
    def list_transactions(self, access_token: str, *, start_date: date, end_date: date, account_ids: Optional[List[str]] = None, offset: int = 0, limit: int = 500) -> List[PlaidTransaction]: ...
    def sync_transactions(self, access_token: str, *, cursor: Optional[str] = None, count: int = 500) -> Dict[str, Any]: ...
    def institution_name_for_item(self, access_token: str) -> Optional[str]: ...
```

---

## services/taxonomy.py

**Role:** Two-level taxonomy in memory; parents & children; prompt helper.

```python
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

@dataclass(frozen=True)
class CategoryNode:
    key: str
    name: str
    description: Optional[str]
    parent_key: Optional[str]
    rules: Optional[List[str]]

class Taxonomy:
    @classmethod
    def from_db(cls, db: "DB") -> "Taxonomy": ...
    @classmethod
    def from_nodes(cls, nodes: Sequence[CategoryNode]) -> "Taxonomy": ...
    def is_valid_key(self, key: str) -> bool: ...
    def get(self, key: str) -> Optional[CategoryNode]: ...
    def children(self, key: str) -> List[CategoryNode]: ...
    def parent(self, key: str) -> Optional[CategoryNode]: ...
    def parents(self) -> List[CategoryNode]: ...
    def all_nodes(self) -> List[CategoryNode]: ...
    def category_id_for_key(self, db: "DB", key: str) -> Optional[int]: ...
    def to_prompt(self, *, include_keys: Optional[Iterable[str]] = None, include_rules: bool = True) -> Dict[str, object]: ...
    def path_str(self, key: str, sep: str = " > ") -> Optional[str]: ...
```

**Depends on:**

* `services.db.DB` (optional helper for id lookup)

---

## services/db.py

**Role:** ORM models + DB façade; **no SQL verification here**; model-only returns.

```python
from typing import Any, ContextManager, Dict, List, Optional, Type, TypeVar
from datetime import date, datetime

M = TypeVar("M")

class Merchant: ...
class Category:  # fields: category_id, parent_id, key, name, description, rules
    ...
class Transaction:  # includes merchant_descriptor, institution, is_verified, etc.
    ...
class Tag: ...
class TransactionTag: ...

class DB:
    def __init__(self, url: str) -> None: ...
    def session(self) -> ContextManager[Any]: ...

    def run_sql(
        self,
        sql: str,
        *,
        model: Type[M],
        pk_column: str,
    ) -> List[M]:
        """Execute a SELECT and return ORM instances of `model`. No verification here."""
        ...

    def fetch_transactions_by_ids_preserving_order(self, ids: List[int]) -> List[Transaction]: ...
    def get_category_id_by_key(self, key: str) -> Optional[int]: ...
    def find_merchant_by_normalized_name(self, normalized_name: str) -> Optional[Merchant]: ...
    def create_merchant(self, *, normalized_name: str, display_name: Optional[str]) -> Merchant: ...
    def get_transaction_by_external(self, *, external_id: str, source: str) -> Optional[Transaction]: ...
    def insert_transaction(self, data: Dict[str, Any]) -> Transaction: ...
    def update_transaction_mutable(self, transaction_id: int, data: Dict[str, Any]) -> Transaction: ...
    def recategorize_unverified_by_merchant(self, merchant_id: int, category_id: int) -> int: ...
    def upsert_tag(self, name: str, description: Optional[str] = None) -> Tag: ...
    def attach_tags(self, transaction_ids: List[int], tag_ids: List[int]) -> int: ...
    def compact_schema_hint(self) -> Dict[str, Any]: ...
```

---

## ui/cli.py

**Role:** `transactoid` CLI entrypoint and commands.

```python
import typer
app = typer.Typer(help="Transactoid — personal finance agent CLI.")

@app.command("ingest")
def ingest(mode: str, data_dir: Optional[str] = None, batch_size: int = 25) -> None: ...

@app.command("ask")
def ask(question: str) -> None: ...

@app.command("recat")
def recat(merchant_id: int, to: str) -> None: ...

@app.command("tag")
def tag(rows: List[int], tags: List[str]) -> None: ...

@app.command("init-db")
def init_db(url: Optional[str] = None) -> None: ...

@app.command("seed-taxonomy")
def seed_taxonomy(yaml_path: str = "configs/taxonomy.yaml") -> None: ...

@app.command("clear-cache")
def clear_cache(namespace: str = "default") -> None: ...

def main() -> None: app()
```

**Depends on:**

* Agents & tools wired at runtime (no logic here)

---

## scripts/seed_taxonomy.py

**Role:** Seed/refresh categories.

```python
def main(yaml_path: str = "configs/taxonomy.yaml") -> None: ...
```

---

## scripts/run.py

**Role:** Orchestrators invoked by CLI or automation.

```python
from typing import Optional, Sequence, List

def run_categorizer(
    *,
    mode: str,
    data_dir: Optional[str] = None,
    account_ids: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
) -> None: ...

def run_analyzer(
    *,
    questions: Optional[List[str]] = None,
) -> None: ...

def run_pipeline(
    *,
    mode: str,
    data_dir: Optional[str] = None,
    account_ids: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
    questions: Optional[List[str]] = None,
) -> None: ...
```

---

## prompts/

* `categorize_prompt.md` — used by Promptorium key **`categorize-transacations`**
* `nl_to_sql_prompt.md` — used by Promptorium key **`nl-to-sql`**
  *(Verify-SQL prompt text is also managed in Promptorium under key **`verify-sql`**.)*

---

## db/schema.sql, db/migrations/

* Tables: `merchants`, `categories` (`key`, `rules` TEXT[]), `transactions` (`merchant_descriptor`, `institution`, `is_verified`), `tags`, `transaction_tags`
* Constraints: `UNIQUE(external_id, source)`, verified immutability (trigger suggested)
* Indexes on typical access paths (posted_at, merchant_id, category_id, is_verified)

---

## configs/, tests/, .env.example, pyproject.toml, README.md

* Standard scaffolding as previously outlined (no code here).

---

If you want, I can now **generate stub files** that exactly match these interfaces, so you can start filling in implementations without chasing types/imports.
