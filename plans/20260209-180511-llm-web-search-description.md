# Persist LLM Web-Search Merchant Description on Categorized Transactions

## Summary
Add a nullable field on `derived_transactions` to store the LLM's web-search-based merchant description, and write it during categorization runs with this rule: persist only when web search was used; clear it otherwise.

## Scope
1. Persist one text field only (no citations, no full trace).
2. Keep markdown formatting as produced by the LLM (`merchant_summary` bullets).
3. Expose in DB only for now (no new UI/API response shaping beyond existing ORM/query access).

## Implementation Plan
1. Add schema column in `DerivedTransaction` and migration `006_add_web_search_summary.py`.
2. Add `used_web_search` to `CategorizedTransaction` and infer it from parsed LLM fields.
3. Add batched DB update method for summaries.
4. Write summaries during sync categorization (set when web search used, clear otherwise).
5. Preserve existing summary during default mutation-registry enrichment carry-over.
6. Update legacy `save_transactions`/insert/update paths to keep behavior consistent.
7. Add tests for categorizer, DB save/update, schema hint, and mutation preservation.

## Verification
Run:
- `uv run ruff check .`
- `uv run ruff format .`
- `uv run mypy --config-file mypy.ini .`
- `uv run deadcode .`
- `uv run pytest -q`
