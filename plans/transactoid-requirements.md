Here’s the distilled, final spec for your personal-finance agent—clean, unambiguous, and aligned with every change we made.

# 1) System goal

Ingest personal transactions (CSV or Plaid), normalize them, categorize with a taxonomy-aware LLM (single pass that may self-revise), persist with dedupe and verified-row immutability, then answer NL questions by generating & verifying SQL, executing it, and returning aggregates + sample rows. Workflow is driven by CLI/scripts; no hidden handoffs.

# 2) Architecture & ownership

* **CLI / Scripts control** orchestration. You can run categorizer and analyzer independently or as a pipeline.
* **Agents**:

  * `categorizer`: drives ingest → categorize → persist.
  * `analyzer_tool`: turns NL→SQL, verifies SQL via LLM, and delegates execution to DB.
* **Tools**:

  * Ingest (CSV/Plaid) → `NormalizedTransaction`.
  * Categorizer (single class) → `CategorizedTransaction`.
  * Persist (upsert, immutable verified rows, tagging, bulk recats).
  * Analytics (verifier only; DB executes).
* **Services**:

  * DB (ORM models + `run_sql` → returns model objects only).
  * Taxonomy (two-level: parents and children, `key` everywhere, `rules` as TEXT[]).
  * Plaid client (thin wrapper).
  * File cache (namespaced JSON; stable keys).

# 3) Data model (key fields)

* **transactions**

  * `merchant_descriptor` (not `merchant_description`)
  * `institution` (bank label like “Amex”, “Chase”, …)
  * Uniqueness on `(external_id, source)`; `external_id` is native when available, else a **canonical hash** over `(posted_at, amount_cents, currency, normalized merchant_descriptor, account_id, institution, source)`.
  * `is_verified` rows are immutable (no category/merchant/amount changes).
* **categories**

  * Use `key` (not `code`), e.g., `FOOD.GROCERIES`.
  * Two-level only (parent & children).
  * `rules` = `TEXT[]` (Postgres ARRAY of TEXT).
  * `is_active` is removed.
* **merchants**

  * No `website_url`.
  * `normalized_name`, `display_name`.
* **tags** + **transaction_tags** as usual.

# 4) Ingest requirements

* **CSV mode**

  * Recursively walk a directory of CSVs.
  * Infer `institution` internally (filename/header heuristics).
  * Emit `NormalizedTransaction` with `source="CSV"`, `source_file=<filename>`.
  * If the CSV lacks a stable ID, set `external_id = canonical hash` (same hash rule as Plaid).
* **Plaid mode**

  * Pull by `account_ids` (optional) with optional `start_date`/`end_date`.
  * Use Plaid transaction ID if present; else use the same canonical hash.
  * Set `source="PLAID"`; set `institution` from item metadata.
* **Filtering of verified rows**

  * Defined as an **implementation detail** (not exposed in interfaces). Providers will *eventually* consult the DB to drop already-verified externals before returning, but it’s not required right now.

**NormalizedTransaction (ingest output)**

```
external_id?: str
account_id: str
posted_at: date
amount_cents: int
currency: str
merchant_descriptor: str
source: "CSV" | "PLAID"
source_file?: str
institution: str
```

# 5) Categorization requirements

* **Single concrete `Categorizer` class**; **batch-only** API:

  * Caller passes an iterable; for a single txn, pass `[txn]`.
* **Prompt source**: Promptorium key **`categorize-transacations`** (Promptorium handles versioning).
* **Single OpenAI/Responses call per txn** (read cache before/ write after). If the model judges confidence < threshold, it self-conducts web search and returns **`revised_*`** in the same response.
* **Taxonomy validation**: `taxonomy.is_valid_key(key)` (covers parents & children). No fallback key; if invalid, treat as error and fix upstream/prompt.
* **Confidence threshold**: default 0.70, but only affects the model’s self-revision behavior (the caller still receives one unified output).

**CategorizedTransaction**

```
txn: NormalizedTransaction
category_key: str
category_confidence: float
category_rationale: str
revised_category_key?: str
revised_category_confidence?: float
revised_category_rationale?: str
```

# 6) Persistence requirements

* **Upsert** by `(external_id, source)`.
* **Immutability**: if an existing row is `is_verified = TRUE`, skip updates and record the outcome; tagging is still allowed.
* **Final category choice**: prefer `revised_*` when present; else primary `category_*`.
* **Category mapping**: `categories.key → category_id` must exist (taxonomy seeded before use).
* **Merchant resolution**: derive a deterministic `normalized_name` from `merchant_descriptor` (lowercase, trim, collapse spaces, strip volatile digits, etc.), find/create merchant, set `merchant_id`.
* **Bulk ops**:

  * `bulk_recategorize_by_merchant(merchant_id, category_key, only_unverified=True)` → returns count.
  * `apply_tags(transaction_ids, tag_names)` → idempotent upsert of tags & links.

# 7) Analysis / NL→SQL requirements

* **AnalyzerTool** APIs:

  * `verify_sql(sql)` → public, LLM second-opinion. Primary goal is correctness (read-only rules are embedded in the prompt).
  * `answer(question, aggregate_model, aggregate_row_factory, sample_model=Transaction, sample_pk_column="transaction_id")`

    * Single Promptorium call (`nl-to-sql`) yields **two SQL strings**: `aggregate_sql` and `sample_rows_sql`.
    * Call `verify_sql()` on both.
    * Execute both via **DB.run_sql** (DB does not verify or coerce):

      * Aggregates: use a row-factory bound model (a small dataclass you define) *or* return ORM if aggregates are made ORM-addressable (you elected model-only from DB; if you need non-ORM aggregates, use a dataclass and map rows in the caller).
      * Samples: must select the sample model’s primary key (default `Transaction.transaction_id`), then DB refetches ORM entities and preserves order.
* **AnalyticsTool** exists only as an internal verifier helper (interfaces only) and is not responsible for SQL execution.

# 8) Database façade requirements

* **No verification here** (LLM verification is upstream).
* **`run_sql(sql, model, pk_column)`**: Execute the SELECT, read primary keys from the result, refetch as ORM entities of `model`, and return them **in order**.
* Helper methods: `get_category_id_by_key`, merchant find/create, transaction get/insert/update (mutable only for unverified), recategorize unverified by merchant, tag upsert/attach, `compact_schema_hint` (internal prompt context).

# 9) Taxonomy requirements

* Two levels only (parents & children).
* Public API:

  * `is_valid_key(key)`, `get`, `children`, `parent`, `parents`, `all_nodes`
  * `category_id_for_key(db, key)`
  * `to_prompt(include_keys?, include_rules=True)` → compact dict for LLM context
  * `path_str(key)`
* Each category node:

  ```
  key: str
  name: str
  description?: str
  parent_key?: str
  rules?: list[str]  # Postgres TEXT[] in DB
  ```

# 10) File cache requirements

* `FileCache` with JSON `get/set`, `exists/delete/clear/list_keys/path_for`, and a private `_atomic_writer`.
* `stable_key(payload)` for deterministic cache keys.
* Used by any LLM call site you wire up (Categorizer, Analyzer verifier, NL→SQL).

# 11) CLI and scripts

* **CLI name:** `transactoid`.
* Commands:

  * `ingest --mode csv|plaid [--data-dir ...] [--batch-size N]`
  * `ask "<question>"`
  * `recat --merchant-id <id> --to <CATEGORY_KEY>`
  * `tag --rows <ids> --tags "<names>"`
  * `init-db`
  * `seed-taxonomy [yaml]`
  * `clear-cache [namespace]`
* **Scripts:**

  * `run_categorizer(...)`: perform ingest → categorize → persist (no implicit handoff).
  * `run_analyzer(questions?: list[str])`: run analyzer; if questions provided, seed the session with them; otherwise interactive.
  * `run_pipeline(...)`: ALWAYS run analyzer after categorizer, passing `questions` if provided.

# 12) Prompts (Promptorium keys)

* `categorize-transacations` (txn categorization; single pass with optional `revised_*`).
* `nl-to-sql` (return `aggregate_sql` + `sample_rows_sql`).
* `verify-sql` (LLM second-opinion on safety/correctness; includes read-only expectations and `compact_schema_hint` context).

# 13) Non-requirements & constraints

* No web UI (CLI-only).
* No separate web-search tool files; web search happens **internally** in the LLM (when needed).
* No `OpenAIClient` wrapper class (removed as superfluous); calls can go directly through your chosen Responses API adapter with FileCache where you place it.
* DB does **not** apply SQL verification or coerce limits; that’s handled by analyzer’s LLM verifier + your prompts.
* No generic “fallback category”; LLM is expected to return valid `key`.

# 14) Dependency layering (what to build first)

Bottom leaf modules to build first:

1. `services/file_cache.py`
2. `services/plaid_client.py`
   Then:
3. `services/db.py` (models + façade)
4. `services/taxonomy.py`
5. `tools/ingest/*` → `NormalizedTransaction`
6. `tools/categorize/categorizer_tool.py` → `CategorizedTransaction`
7. `tools/persist/persist_tool.py`
8. `agents/analyzer_tool.py` (verify & answer) → uses DB.run_sql
9. `scripts` and `ui/cli.py`

---

If you want, I can now generate **stub modules** for every file with the exact interfaces above so you can start implementing against them immediately.
