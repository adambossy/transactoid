---
name: migrate-taxonomy
description: Orchestrate a taxonomy migration end-to-end — invoke the migrate_taxonomy tool, then propagate updates to dependent artifacts (configs, workspace taxonomy rules, merchant rules, budget, agent memory).
when_to_use: When the user asks to add, remove, rename, merge, split, or deprecate a taxonomy category, or restructure the category hierarchy.
---

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

A taxonomy migration touches multiple layers. The `migrate_taxonomy` tool handles the database and transaction reassignment. Everything else is this skill's responsibility:

| Artifact | Handled by `migrate_taxonomy` tool | Handled by this skill |
|---|---|---|
| Database (categories table) | Yes | - |
| Transactions (reassignment) | Yes | - |
| Categorization cache | Yes (cleared) | - |
| `.transactoid/memory/merchant-rules.md` | - | Yes (via `edit-merchant-rules-memory` skill) |
| `configs/merchant-rules.md` | - | Yes |
| `configs/taxonomy.yaml` | - | Yes |
| `$PENNY_WORKSPACE/memory/taxonomy-rules.md` | - | Yes |
| `.transactoid/memory/budget.md` | - | Regenerate if affected (via `generate-budget` skill) |

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

Call the `migrate_taxonomy` MCP tool with the appropriate operation. This handles the database changes and transaction reassignment.

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
Use `remove` with a `fallback_key` to reassign transactions, then mark the category as deprecated:
```sql
UPDATE categories SET deprecated_at = NOW() WHERE key = '<old_key>'
```
The deprecated row stays in the database (preserving FK integrity with the `transaction_category_events` audit log) but is excluded from `fetch_categories()`, `{{CATEGORY_TAXONOMY}}` prompt injection, and agent SQL queries (via `WHERE c.deprecated_at IS NULL`).

### Step 3: Update `configs/taxonomy.yaml`

The migration tool updates the database but does NOT update the YAML config. Edit the file to match:

- **Add**: Insert the new category entry in the correct position
- **Remove/Deprecate**: Delete the entry from the YAML
- **Rename**: Update the `key` field (and `parent_key` references in children)
- **Merge**: Remove source entries, keep target
- **Split**: Remove source entry, add target entries

### Step 4: Update merchant rules

Use the `edit-merchant-rules-memory` skill to update category keys in `.transactoid/memory/merchant-rules.md`. For each rule that references an old/removed category key, update it to the new key.

Also update `configs/merchant-rules.md` (a separate checked-in file) manually:

```bash
grep -n "<old_category_key>" configs/merchant-rules.md
```

Replace old category keys with new ones in any matching rules.

### Step 5: Update the taxonomy rules in the workspace

The taxonomy rules describe the categories in natural language for the LLM
categorizer. They live in the **workspace**, not in the codebase as prompts:

```
$PENNY_WORKSPACE/memory/taxonomy-rules.md      (default: ~/.transactoid/memory/taxonomy-rules.md)
```

Update this single file whenever categories change. It is plain **Markdown** —
no YAML front matter, no HTML tags.

1. **Targeted edit** — for a single add/remove/rename/merge/split, edit the file
   directly: add, drop, or rename the affected category's definition (and fix any
   references to it in the decision-order / overlap sections) so the prose matches
   the new taxonomy.

2. **Full regeneration** — for large-scale changes, regenerate the whole document
   from the current (production) taxonomy. The `categories` table is the source of
   truth: read every active category (`deprecated_at IS NULL`) with its `key`,
   `name`, `description`, and parent, and render Markdown grouped top-level →
   sub-category, with each category's `description` as its definition. Carry over
   the global decision-order / overlap-resolution / edge-case guidance, adapting
   any category names that changed. Write the result to the workspace path above.

   ```sql
   SELECT p.key AS parent_key, p.name AS parent_name,
          c.key, c.name, c.description
   FROM categories c
   LEFT JOIN categories p ON p.category_id = c.parent_id
   WHERE c.deprecated_at IS NULL
   ORDER BY COALESCE(p.key, c.key), c.parent_id NULLS FIRST, c.key
   ```

   Note: the old LLM pipeline (`penny/taxonomy/generator.py`) is unused, has no
   committed prompt template, and emitted YAML front matter — do **not** use it.
   Generate the Markdown directly from the DB taxonomy as described above.

### Step 6: Regenerate budget (if affected)

If the migration touched categories that appear in the budget, regenerate it using the `generate-budget` skill. Check first:

```bash
grep -i "<category_name>" .transactoid/memory/budget.md
```

If matches are found, the budget is stale and should be regenerated.

### Step 7: Verify

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
   grep -r "<old_key>" configs/ "${PENNY_WORKSPACE:-$HOME/.transactoid}/memory/"
   ```

4. **Report results to user**: transaction count moved, merchant rules updated, config files changed.

## Example: Merge Overlapping Categories

**User**: "Merge childcare_and_babysitting into childcare.care"

1. Query transactions under `education_and_childcare.childcare_and_babysitting` -> 30 transactions, 14 merchants
2. Present impact: "30 transactions across 14 merchants will move to childcare.care"
3. Call `migrate_taxonomy` with `{"operation": "merge", "source_keys": ["education_and_childcare.childcare_and_babysitting"], "target_key": "childcare.care"}`
4. Remove entry from `configs/taxonomy.yaml`
5. Use `edit-merchant-rules-memory` skill to update `.transactoid/memory/merchant-rules.md`
6. Update `configs/merchant-rules.md` (Julia nanny rule -> `childcare.care`)
7. Remove the entry from `$PENNY_WORKSPACE/memory/taxonomy-rules.md`
8. Verify: 0 transactions remain on old key, no stale references

## Important Notes

- **Always present impact before executing**: Taxonomy changes can affect many transactions and downstream artifacts.
- **Two merchant-rules files exist**: `configs/merchant-rules.md` (checked in) and `.transactoid/memory/merchant-rules.md` (agent memory). Both must be updated.
- **Taxonomy rules live in the workspace**: edit `$PENNY_WORKSPACE/memory/taxonomy-rules.md` (plain Markdown, no front matter), not the codebase prompts.
- **Budget becomes stale**: After any migration affecting budgeted categories, regenerate using the `generate-budget` skill.
- **`configs/taxonomy.yaml` is not auto-synced**: The migration tool operates on the database. Always update the YAML to keep it in sync.