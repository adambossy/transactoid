# Transactoid Plan: Interfaces & Requirements

This single plan merges the previous interface and requirement specs so each module’s surface area sits directly beside the rules it must honor.

## 1. System Overview

### Goal
Ingest personal transactions (CSV or Plaid), normalize them, categorize with a taxonomy-aware LLM (single pass with optional self-revision), persist them with dedupe and verified-row immutability, then answer natural-language questions by generating SQL, executing it, and returning aggregates plus sample rows. The workflow is orchestrated entirely through CLI commands or scripts with no hidden handoffs.

### Architecture & Ownership
* **CLI / scripts** coordinate the full sync → categorize → persist → analyze pipeline.
* **Agents**
  * `transactoid`: core agent loop with natural language analytics via prompt.
* **Tools**
  * Sync tool fetches transactions from Plaid and emits `Transaction` batches.
  * Categorizer returns `CategorizedTransaction` instances.
  * Persist tool upserts with dedupe, enforces immutability, manages tagging and recategorization.
* **Services**
  * DB façade (ORM models + `run_sql` returning model objects).
  * Taxonomy (two-level, `key`-based, `rules` stored as `TEXT[]`).
  * Plaid client wrapper.
  * File cache with namespaced JSON storage and deterministic keys.

### Directory Layout
```
transactoid/
├─ agents/
│  └─ transactoid.py
├─ tools/
│  ├─ sync/
│  │  └─ sync_tool.py
│  ├─ categorize/
│  │  └─ categorizer_tool.py
│  └─ persist/
│     └─ persist_tool.py
├─ services/
│  ├─ file_cache.py
│  ├─ plaid_client.py
│  ├─ taxonomy.py
│  └─ db.py
├─ db/
│  ├─ schema.sql
│  └─ migrations/
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

### Workflow Pillars
1. Ingest transactions from CSV directories or Plaid.
2. Normalize into `NormalizedTransaction` batches.
3. Categorize each transaction with taxonomy validation and optional self-revision.
4. Persist results (upsert, dedupe, tagging, immutability guarantees).
5. Answer natural language questions using `DB.run_sql`.

## 2. Data Model (Key Fields)
* **transactions**
  * `merchant_descriptor` and `institution` fields.
  * `(external_id, source)` uniqueness; derive canonical hash when the external ID is missing (hash over `posted_at`, `amount_cents`, `currency`, normalized `merchant_descriptor`, `account_id`, `institution`, `source`).
  * `is_verified` rows are immutable (no category/merchant/amount changes).
* **categories**
  * `key` (two-level: parent and child) with `rules` stored as `TEXT[]`.
  * `is_active` removed.
* **merchants**
  * Store `normalized_name` and `display_name`; omit `website_url`.
* **tags** / **transaction_tags** remain standard for tagging support.

## 3. Module-by-Module Interfaces & Requirements

### Agents

#### `agents/transactoid.py`
**Interface**
```python
from __future__ import annotations
from typing import Optional

class TransactoidAgent:
    def __init__(
        self,
        *,
        model_name: str = "gpt-5",
        prompt_key_categorize: str = "categorize-transacations",
        confidence_threshold: float = 0.70,
    ) -> None: ...

    def run(self, *, batch_size: int = 25) -> None: ...
```

**Requirements**
* Use the categorizer to process transaction batches, then persist outcomes.
* Inject `Taxonomy` into the categorizer.
* Respect CLI-provided batch sizing and confidence threshold settings.

### Tools — Sync

#### `tools/sync/sync_tool.py`
**Interface**
```python
from dataclasses import dataclass
from typing import List

@dataclass
class SyncResult:
    categorized_added: list[CategorizedTransaction]
    categorized_modified: list[CategorizedTransaction]
    removed_transaction_ids: list[str]
    next_cursor: str
    has_more: bool

class SyncTool:
    def __init__(
        self,
        plaid_client: PlaidClient,
        categorizer: Categorizer,
        db: DB,
        taxonomy: Taxonomy,
        *,
        access_token: str,
        cursor: str | None = None,
    ) -> None: ...

    def sync(self, *, count: int = 25) -> list[SyncResult]: ...
```

**Requirements**
* Call Plaid's transaction sync API with automatic pagination.
* Categorize each page of transactions as it's fetched.
* Persist categorized transactions to the database.
* Handle Plaid's `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION` error with retries.

### Tools — Categorize

#### `tools/categorize/categorizer_tool.py`
**Interface**
```python
from dataclasses import dataclass
from typing import Iterable, Optional, List
from models.transaction import Transaction

@dataclass
class CategorizedTransaction:
    txn: Transaction
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

    def categorize(self, txns: Iterable[Transaction]) -> List[CategorizedTransaction]: ...
```

**Requirements**
* Provide a single concrete, batch-only API (wrap single transactions in a list).
* Read from and write to the file cache around each LLM call; only one OpenAI/Responses call per transaction.
* When model confidence falls below the threshold, allow the model to self-revise via web search, returning `revised_*` fields in the same response.
* Validate category keys with `taxonomy.is_valid_key`; invalid keys are treated as errors to resolve upstream.

### Tools — Persist

#### `tools/persist/persist_tool.py`
**Interface**
```python
from dataclasses import dataclass
from typing import Iterable, List
from tools.categorize.categorizer_tool import CategorizedTransaction

@dataclass
class SaveRowOutcome:
    external_id: str
    source: str
    action: str
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

**Requirements**
* Upsert on `(external_id, source)`.
* Skip updates to rows marked `is_verified = TRUE`, but continue to allow tagging.
* Favor `revised_*` category fields when present; otherwise fall back to primary category values.
* Resolve merchants by deterministic normalization of `merchant_descriptor` (lowercase, trim, collapse spaces, strip volatile digits, etc.) before find/create.
* Support bulk operations for recategorization and tag application, returning counts/outcomes.

### Services — Infrastructure

#### `services/file_cache.py`
**Interface**
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

**Requirements**
* Provide deterministic cache keys via `stable_key`.
* Use atomic writes to avoid partial files.
* Support being shared across all LLM call sites (categorizer, agent).

#### `services/plaid_client.py`
**Interface**
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
    def __init__(
        self,
        *,
        client_id: str,
        secret: str,
        env: PlaidEnv = "sandbox",
        client_name: str = "transactoid",
        products: Optional[List[str]] = None,
    ) -> None: ...
    def create_link_token(self, *, user_id: str, redirect_uri: Optional[str] = None) -> str: ...
    def exchange_public_token(self, public_token: str) -> Dict[str, str]: ...
    def get_accounts(self, access_token: str) -> List[PlaidAccount]: ...
    def get_item_info(self, access_token: str) -> PlaidItemInfo: ...
    def list_transactions(
        self,
        access_token: str,
        *,
        start_date: date,
        end_date: date,
        account_ids: Optional[List[str]] = None,
        offset: int = 0,
        limit: int = 500,
    ) -> List[PlaidTransaction]: ...
    def sync_transactions(self, access_token: str, *, cursor: Optional[str] = None, count: int = 500) -> Dict[str, Any]: ...
    def institution_name_for_item(self, access_token: str) -> Optional[str]: ...
```

**Requirements**
* Act as a thin wrapper over Plaid’s APIs; no LLM involvement.
* Surface institution names for transaction metadata population.

#### `services/taxonomy.py`
**Interface**
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
    def to_prompt(
        self,
        *,
        include_keys: Optional[Iterable[str]] = None,
        include_rules: bool = True,
    ) -> Dict[str, object]: ...
    def path_str(self, key: str, sep: str = " > ") -> Optional[str]: ...
```

**Requirements**
* Enforce a two-level taxonomy (parents and children only).
* Provide prompt-friendly serializations and helper lookups used by categorizer and `DB.run_sql`.

#### `services/db.py`
**Interface**
```python
from typing import Any, ContextManager, Dict, List, Optional, Type, TypeVar
from datetime import date, datetime

M = TypeVar("M")

class Merchant: ...
class Category: ...
class Transaction: ...
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
    ) -> List[M]: ...

    def fetch_transactions_by_ids_preserving_order(self, ids: List[int]) -> List[Transaction]: ...
    def get_category_id_by_key(self, key: str) -> Optional[int]: ...
    def find_merchant_by_normalized_name(self, normalized_name: str) -> Optional[Merchant]: ...
    def create_merchant(
        self,
        *,
        normalized_name: str,
        display_name: Optional[str],
    ) -> Merchant: ...
    def get_transaction_by_external(
        self,
        *,
        external_id: str,
        source: str,
    ) -> Optional[Transaction]: ...
    def insert_transaction(self, data: Dict[str, Any]) -> Transaction: ...
    def update_transaction_mutable(self, transaction_id: int, data: Dict[str, Any]) -> Transaction: ...
    def recategorize_unverified_by_merchant(
        self,
        merchant_id: int,
        category_id: int,
    ) -> int: ...
    def upsert_tag(
        self,
        name: str,
        description: Optional[str] = None,
    ) -> Tag: ...
    def attach_tags(self, transaction_ids: List[int], tag_ids: List[int]) -> int: ...
    def compact_schema_hint(self) -> Dict[str, Any]: ...
```

**Requirements**
* `run_sql` must execute raw SELECTs, collect primary keys, refetch ORM entities, and return them in order.
* Provide helpers for category lookup, merchant normalization, transaction upsert/update (mutable only for unverified rows), recategorization, tag management, and prompt context (`compact_schema_hint`).

### UI & CLI

#### `ui/cli.py`
**Interface**
```python
import typer

app = typer.Typer(help="Transactoid — personal finance agent CLI.")

@app.command("sync")
def sync(access_token: str, cursor: Optional[str] = None, count: int = 500) -> None: ...

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

**Requirements**
* Provide CLI commands `sync`, `ask`, `recat`, `tag`, `init-db`, `seed-taxonomy`, and `clear-cache`.
* Wire commands to orchestrator helpers without embedding business logic.

### Scripts

#### `scripts/seed_taxonomy.py`
**Interface**
```python
def main(yaml_path: str = "configs/taxonomy.yaml") -> None: ...
```

**Requirements**
* Seed or refresh the taxonomy from a YAML file (default `configs/taxonomy.yaml`).

#### `scripts/run.py`
**Interface**
```python
from typing import Optional, Sequence, List

def run_categorizer(
    *,
    access_token: str,
    cursor: Optional[str] = None,
    account_ids: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
) -> None: ...

def run_pipeline(
    *,
    access_token: str,
    cursor: Optional[str] = None,
    account_ids: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    batch_size: int = 25,
    confidence_threshold: float = 0.70,
    questions: Optional[List[str]] = None,
) -> None: ...
```

**Requirements**
* `run_categorizer` performs ingest → categorize → persist with explicit parameter control.
* `run_pipeline` runs categorization and then launches the agent, forwarding optional question seeds.

### Database Assets

#### `db/schema.sql` & `db/migrations/`
**Requirements**
* Define tables `merchants`, `categories`, `transactions`, `tags`, and `transaction_tags`.
* Enforce `(external_id, source)` uniqueness and immutability for verified rows (trigger recommended).
* Index common access paths (posted date, merchant, category, verification status).

### Supporting Config & Prompts

#### File Cache Usage
* Apply the JSON file cache across categorizer and agent LLM calls.
* Provide namespace-aware CRUD plus `clear` and `list_keys` helpers for CLI tooling.

#### Promptorium Keys
* `categorize-transacations` for transaction categorization (single pass + optional `revised_*`).

### Non-requirements & Constraints
* CLI-only interface; no web UI.
* No dedicated web-search tool files—LLM handles search internally when confidence is low.
* No `OpenAIClient` wrapper; call Responses API adapters directly alongside `FileCache` integration.
* No fallback "misc" category; the LLM must return valid taxonomy keys.

### Dependency Layering (Build Order)
1. `services/file_cache.py`
2. `services/plaid_client.py`
3. `services/db.py`
4. `services/taxonomy.py`
5. `tools/sync/sync_tool.py`
6. `tools/categorize/categorizer_tool.py`
7. `tools/persist/persist_tool.py`
8. `agents/transactoid.py`
9. `scripts/*` and `ui/cli.py`

This ordering builds foundational services first, then upstream tools, and finally orchestration layers.
