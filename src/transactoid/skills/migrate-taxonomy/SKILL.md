# Skill: Migrate Taxonomy

## Purpose

Orchestrate a complete taxonomy migration end-to-end: execute the structural change via the `migrate_taxonomy` MCP tool, then propagate updates to all dependent artifacts (config files, prompts, merchant rules, budget, agent memory).

## When to Use

Use this skill when:
- A user asks to add, remove, rename, merge, split, or deprecate a category
- Two categories overlap and need to be consolidated
- A category needs to be retired (soft-deleted)
- The taxonomy structure needs reorganization

## What Gets Impacted

A taxonomy migration touches multiple layers. The `migrate_taxonomy` tool handles some automatically, but several artifacts require manual follow-up:

| Artifact | Auto-updated by tool? | Manual step needed? |
|---|---|---|
| Database (categories table) | Yes | No |
| Transactions (reassignment) | Yes | No |
| `.transactoid/memory/merchant-rules.md` | Yes (via MerchantRulesLoader) | Verify |
| `configs/merchant-rules.md` | **No** | Yes |
| `configs/taxonomy.yaml` | **No** | Yes |
| Taxonomy rules prompts | **No** | Yes |
| `.transactoid/memory/budget.md` | **No** | Regenerate if affected |
| Categorization cache | Yes (cleared) | No |

## Workflow

### Step 1: Assess the migration

Before making changes, understand the scope:

1. **Identify affected transactions**:
   ```sql
   SELECT c.key, c.name, COUNT(dt.transaction_id) as tx_count
   FROM categories c
   LEFT JOIN derived_transactions dt ON dt.category_id = c.category_id
   WHERE c.key IN ('<source_key>', '<target_key>')
   GROUP BY c.key, c.name
   ```

2. **Identify affected merchant rules**:
   ```bash
   grep -i "<category_key>" .transactoid/memory/merchant-rules.md
   grep -i "<category_key>" configs/merchant-rules.md
   ```

3. **Check for budget impact**:
   ```bash
   grep -i "<category_display_name>" .transactoid/memory/budget.md
   ```

4. **Present the impact summary to the user** before proceeding. Include:
   - Number of transactions affected
   - Merchant rules that will change
   - Whether budget will need regeneration

### Step 2: Execute the migration tool

Call the `migrate_taxonomy` MCP tool with the appropriate operation:

**Add:**
```json
{"operation": "add", "key": "parent.child", "name": "Display Name", "parent_key": "parent", "description": "..."}
```

**Remove:**
```json
{"operation": "remove", "key": "parent.old_child", "fallback_key": "parent.new_child"}
```

**Rename:**
```json
{"operation": "rename", "old_key": "old.key", "new_key": "new.key"}
```

**Merge:**
```json
{"operation": "merge", "source_keys": ["a.old1", "a.old2"], "target_key": "a.target", "recategorize": false}
```

**Split:**
```json
{"operation": "split", "source_key": "a.broad", "targets": [["a.specific1", "Name 1", null], ["a.specific2", "Name 2", null]]}
```

**Deprecate (soft-delete):**
The `migrate_taxonomy` tool does not support deprecation directly. For deprecation:
1. Recategorize all transactions from the old category to the new one using `recategorize_merchant` for each affected merchant (see the `recategorize-merchant` skill)
2. Mark the category as deprecated in the database:
   ```sql
   UPDATE categories SET deprecated_at = NOW() WHERE key = '<old_key>'
   ```

### Step 3: Update `configs/taxonomy.yaml`

The migration tool updates the database but does NOT update the YAML config. Edit the file to match:

- **Add**: Insert the new category entry in the correct position
- **Remove/Deprecate**: Delete the entry from the YAML
- **Rename**: Update the `key` field (and `parent_key` references in children)
- **Merge**: Remove source entries, keep target
- **Split**: Remove source entry, add target entries

### Step 4: Update `configs/merchant-rules.md`

The migration tool updates `.transactoid/memory/merchant-rules.md` automatically, but `configs/merchant-rules.md` is a separate checked-in file. Update it manually:

```bash
grep -n "<old_category_key>" configs/merchant-rules.md
```

Replace old category keys with new ones in any matching rules.

### Step 5: Update taxonomy rules prompts

The taxonomy rules prompts describe categories in natural language for the LLM categorizer. They must be updated when categories change.

1. Edit the **latest versioned prompt** (check which is latest):
   ```bash
   ls src/transactoid/prompts/taxonomy-rules/
   ```
   Edit the highest-numbered version to add/remove/rename the subcategory description.

2. Edit the **top-level prompt** (the working copy):
   ```
   prompts/taxonomy-rules.md
   ```
   Make the same change here.

3. Optionally regenerate from scratch:
   ```bash
   uv run python scripts/build_taxonomy.py
   ```
   This uses the LLM to regenerate the full taxonomy rules from `configs/taxonomy.yaml`. Only needed for large-scale changes.

### Step 6: Update `.transactoid/memory/merchant-rules.md` (verify)

The migration tool's `MerchantRulesLoader` auto-updates category keys in this file. Verify the update was applied:

```bash
grep -i "<old_key>" .transactoid/memory/merchant-rules.md
```

If any stale keys remain, update them manually using the `edit-merchant-rules-memory` skill.

### Step 7: Regenerate budget (if affected)

If the migration touched categories that appear in the budget, regenerate it using the `generate-budget` skill. Check first:

```bash
grep -i "<category_name>" .transactoid/memory/budget.md
```

If matches are found, the budget is stale and should be regenerated.

### Step 8: Verify

Run verification queries to confirm the migration is complete:

1. **No transactions on old category** (for remove/merge/deprecate):
   ```sql
   SELECT COUNT(*) FROM derived_transactions dt
   JOIN categories c ON dt.category_id = c.category_id
   WHERE c.key = '<old_key>'
   ```

2. **Deprecated flag set** (for deprecation):
   ```sql
   SELECT key, deprecated_at FROM categories WHERE key = '<old_key>'
   ```

3. **No stale references in config files**:
   ```bash
   grep -r "<old_key>" configs/ .transactoid/memory/ prompts/
   ```

4. **Report results to user**: transaction count moved, merchant rules updated, config files changed.

## Deprecation-Specific Workflow

When deprecating (soft-deleting) a category rather than hard-removing it:

1. **Recategorize transactions**: For each merchant under the old category, use the `recategorize-merchant` skill to move transactions to the new category and persist the merchant rule.

2. **Mark deprecated in DB**:
   ```sql
   UPDATE categories SET deprecated_at = NOW() WHERE key = '<old_key>'
   ```

3. **Follow Steps 3-8 above** to update configs, prompts, and memory files.

The deprecated category row stays in the `categories` table (preserving FK integrity with `transaction_category_events` audit log) but is excluded from:
- `fetch_categories()` (filtered by default)
- `{{CATEGORY_TAXONOMY}}` prompt injection
- Agent SQL queries (via `WHERE c.deprecated_at IS NULL` directive)

## Example: Merge Overlapping Categories

**User**: "Merge childcare_and_babysitting into childcare.care"

1. Query transactions under `education_and_childcare.childcare_and_babysitting` -> 30 transactions, 14 merchants
2. Present impact: "30 transactions across 14 merchants will move to childcare.care"
3. Recategorize each merchant via `recategorize_merchant` MCP tool
4. Mark old category deprecated: `UPDATE categories SET deprecated_at = NOW() WHERE key = '...'`
5. Remove entry from `configs/taxonomy.yaml`
6. Update `configs/merchant-rules.md` (Julia nanny rule -> `childcare.care`)
7. Update `.transactoid/memory/merchant-rules.md` (Tameka rule -> `childcare.care`)
8. Remove from `prompts/taxonomy-rules.md` and versioned copy
9. Verify: 0 transactions remain, deprecated_at is set, no stale references

## Important Notes

- **Always present impact before executing**: Taxonomy changes can affect many transactions and downstream artifacts.
- **Deprecation preserves audit trail**: The `transaction_category_events` table stores category keys as strings, so history is readable even after the category is deprecated.
- **Two merchant-rules files exist**: `configs/merchant-rules.md` (checked in) and `.transactoid/memory/merchant-rules.md` (agent memory). Both must be updated.
- **Taxonomy rules are versioned**: Edit the latest version in `src/transactoid/prompts/taxonomy-rules/` and the working copy in `prompts/taxonomy-rules.md`.
- **Budget becomes stale**: After any migration affecting budgeted categories, regenerate using the `generate-budget` skill.
- **`configs/taxonomy.yaml` is not auto-synced**: The migration tool operates on the database. Always update the YAML to keep it in sync.
