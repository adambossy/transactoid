# Skill: Generate Budget

## Purpose

Generate a complete, category-aware budget from historical transaction data.
This skill produces a consistent markdown table that covers all categories and
subcategories so no spending area is omitted.

## When to Use

Use this skill when:
- A user asks to create or refresh a budget
- A user asks for category-by-category spending targets
- A user asks for a full monthly spending plan based on their history

## Required Inputs

1. **history_window_months** (int): Number of months of history to use (must be 3-12)
2. **as_of_date** (str): Budget reference date in `YYYY-MM-DD`
3. **budget_strategy** (str): Strategy name (e.g., `historical_mean`, `conservative`, `growth`)
4. **rounding_increment** (int): Target rounding unit in dollars (e.g., `5`, `10`, `25`)

## Guardrails

- Always use a sufficiently large sample window of **3 to 12 months**.
- Never produce a partial budget: include **all categories and subcategories** from taxonomy.
- Keep category display labels consistent with taxonomy display names.
- Use spending transactions (positive outflows) for baseline budgeting unless user asks for net.
- If available history is less than 3 months, warn the user and provide a provisional budget.

## Data Collection Workflow

1. Select analysis window:
   - Default to 6 months if user does not specify.
   - Clamp user-provided values to the 3-12 month range.

2. Pull taxonomy coverage:
   - Enumerate all categories and subcategories that should appear in output.
   - Keep parent/child relationships intact for readability.

3. Pull spending history:
   - Aggregate monthly spending by category over the full window.
   - Include months with zero spend so averages are not inflated.

4. Compute budget targets:
   - Base target: historical monthly mean.
   - Optional strategy adjustment: conservative buffer or growth reduction.
   - Round to configured increment for cleaner targets.

5. Render consistently:
   - Return one canonical markdown table format.
   - Keep column order and number formatting stable across runs.

## Output Format

Always render budget rows in markdown table format:

```md
| Category | Subcategory | Avg Monthly Spend | Proposed Budget | Delta | Notes |
|---|---|---:|---:|---:|---|
| Food & Dining | Groceries | $620 | $625 | +$5 | Stable baseline |
| Food & Dining | Restaurants | $410 | $350 | -$60 | Reduction target |
```

Formatting rules:
- `Category` and `Subcategory` columns are always present
- Currency uses `$` and whole dollars unless cents are explicitly required
- `Delta = Proposed Budget - Avg Monthly Spend`
- Keep row ordering deterministic (category then subcategory)

## Validation Checklist

Before returning the budget:

1. Coverage validation
   - Confirm every category/subcategory from taxonomy appears exactly once.

2. Window validation
   - Confirm sample window is between 3 and 12 months.
   - Confirm output states the exact date range used.

3. Consistency validation
   - Confirm markdown table columns and order match the canonical format.
   - Confirm currency and delta formatting are consistent for all rows.

## Example User Response Pattern

- Summary: state window, strategy, and top over/under allocations.
- Table: include the full markdown budget table.
- Follow-up: offer refinements (e.g., tighten discretionary categories by 10%).
