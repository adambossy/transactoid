# Categorizer Provenance + Multi-Model Implementation Plan

## Scope
- Add category provenance metadata and event history.
- Persist literal categorizer model per transaction.
- Support categorizer provider selection aligned with core runtime env contract.
- Backfill existing categorized transactions with current OpenAI categorizer model (`gpt-5.2`) for NULL model rows.

## Decisions
- Current-state provenance on `derived_transactions`:
  - `category_model` (nullable text)
  - `category_method` (nullable enum-like text)
  - `category_assigned_at` (nullable timestamp)
- Append-only history table `transaction_category_events` with category key snapshots.
- Allowed methods: `llm`, `manual`, `taxonomy_migration`.
- Manual/taxonomy writes preserve existing `category_model`.
- LLM writes set `category_model` to the literal runtime model string.

## Implementation
1. Add DB model fields and new `TransactionCategoryEvent` model with constraints/indexes.
2. Add Alembic migration:
   - schema changes
   - constraints/indexes
   - backfill of current-state columns
   - bootstrap category events for existing categorized rows
3. Refactor DB facade category-update paths to atomic update+event write:
   - `bulk_update_derived_categories`
   - `recategorize_merchant`
   - `reassign_transactions_to_category`
4. Update categorizer output to carry `category_model`.
5. Update sync and legacy save paths to pass method/model/reason metadata.
6. Add provider-aware categorizer config:
   - openai path (existing)
   - gemini path via `google.genai`
   - claude path fail-fast (consistent with branch runtime state)
7. Add/adjust tests for provenance and model recording.

## Verification
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run mypy --config-file mypy.ini .`
- `uv run deadcode .`
- `uv run pytest -q`
