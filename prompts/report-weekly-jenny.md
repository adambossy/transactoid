# Weekly Spending Summary for Jenny

Generate a weekly spending summary for the week ending {{CURRENT_DATE}}.
Send the final report to jloleary0@gmail.com with subject "Weekly Spending Summary 📊".

## Budget

Check if `memory/budget.md` exists. If it does, read it for monthly budget targets.
Derive a 30-day target directly from the monthly figure, and a 7-day target by multiplying monthly × (7 / 30.44).
If the file does not exist, omit all budget comparison columns from the report.

---

## Report Sections to Generate

### 1. Shopping & Food — Last 7 Days

Show spending over the last 7 days for two top-level categories only:
- **Food & Dining** (and each subcategory with any spend)
- **Shopping** (and each subcategory with any spend)

Present as a table with columns: Category | Subcategory | 7-Day Spend.
Add a subtotal row for each top-level category.
Below the table, list the top 2–3 merchants by spend within Food & Dining and within Shopping.

### 2. Budget Status Table — Last 30 Days

Produce an HTML `<table>` (not markdown) with these columns:

1. **Category / Subcategory** — the category name
2. **Status** — a `<td>` whose `background-color` CSS reflects how actual 30-day spend
   compares to the monthly budget target:
   - 25%+ under budget: `#1a7a1a` (dark green), white text
   - 10–25% under budget: `#52b752` (medium green), white text
   - 0–10% under budget: `#c8e6c9` (light green), black text
   - 0–10% over budget: `#ffcdd2` (light red), black text
   - 10–25% over budget: `#e05c5c` (medium red), white text
   - 25%+ over budget: `#b71c1c` (dark red), white text
   - Put the % deviation inside the cell (e.g. `−12%` or `+18%`)
3. **Budget** — monthly target from budget.md
4. **30-Day Actual** — actual spend for the last 30 days
5. **Difference** — dollar delta (actual − budget), prefixed with + or −

Include every category from budget.md that had spend in the last 30 days.
Skip zero-spend rows.
Add a **Total** row at the bottom spanning all budget rows.

### 3. Recommendations for the Next 15 Days

Analyze spending from the last 15 days and write 4–6 short, friendly, concrete tips for
staying on track for the rest of the month. Use "we" where natural. Name specific
merchants or categories. Be encouraging, not scolding.

---

## Tone and Format

- Friendly and personal — this report goes to Jenny, not a finance analyst.
- Sections 1 and 3 may be markdown; Section 2 **must be the raw HTML table** so colored cells render in email.
- Wrap the entire report in clean HTML with inline CSS suitable for email clients (no external stylesheets, no JavaScript).
- Keep the layout simple: a header with the date range, then the three sections in order.

---

## After Generating the Report

1. Include the full HTML in your final response.
2. Write the HTML file to `.transactoid/reports/report-weekly-jenny-latest.html` using `execute_shell_command`.
3. Send the report by email to jloleary0@gmail.com with subject "Weekly Spending Summary 📊".
