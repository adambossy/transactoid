# Weekly Spending Report

Generate a comprehensive spending report for the week ending {{CURRENT_DATE}}.

## Budget

Check if `memory/budget.md` exists. If it does, read it to get budget targets (the file stores monthly figures — derive weekly targets by dividing by 4.33). If the file does not exist, omit all budget comparisons from the report.

## What I Consider "Unusual"

- Any single transaction over $500 that isn't recurring (rent, car payment, etc.)
- Any merchant I've never transacted with before that has charges over $100
- Any category where spending is 50% or more above the 4-week average
- Duplicate charges from the same merchant on the same day

---

## Report Sections to Generate

Please analyze my transaction data and generate a report with these sections:

### 1. Executive Summary
- Total spending this week vs. last week (amount and % change)
- Top 3 areas of concern (overspending or unusual patterns)
- Top 3 positive trends (good spending habits or savings)
- If budget data is available: am I on track to meet my weekly target?

### 2. Category Spending Breakdown
For each major category:
- Amount spent this week
- If budget data is available: budget target vs. actual (over/under)
- Comparison to 4-week average
- Flag any category where I'm spending 50%+ above average

### 3. Spending Trends (4, 8, and 12 weeks)
For each category with significant data:
- **Overspending trend**: Categories where spending has been consistently increasing
- **Underspending trend**: Categories where I'm spending less than usual (potential savings)
- **Stable trend**: Categories where spending is consistent
- Include specific numbers and percentages

### 4. Unusual or Major Expenses
List any transactions that meet my "unusual" criteria above:
- Transaction date, merchant, amount, category
- Why it's flagged (first-time merchant, unusually high, duplicate, etc.)
- Whether it seems like a one-time expense or something to watch

### 5. Predicted Upcoming Expenses
Based on historical patterns:
- **Recurring subscriptions/bills**: What's due in the next 7 days?
- **Weekly patterns**: Based on recent weeks, what should I expect?
- **Upcoming large expenses**: Any known annual/monthly charges coming soon?

### 6. Actionable Recommendations
Be specific and honest:
- **Cut back on**: Specific merchants or categories where I'm overspending
- **Maintain**: Areas where my spending is healthy and aligned with goals
- **OK to splurge**: Where I can afford to spend more without guilt
- **Watch out for**: Potential issues or creeping expenses to monitor

---

## Output Format

Format the report in clean markdown suitable for email delivery. Use tables for numerical comparisons where appropriate. Include actual dollar amounts, percentages, and specific merchant names. Be direct and honest about overspending - I want actionable insights, not sugar-coated summaries.

---

## After Generating the Report

Once you have produced the markdown report above:

1. Include the full markdown report in your final response.
2. Convert the markdown report to a styled HTML document following the render-report-html skill instructions (consult `src/transactoid/skills/render-report-html/SKILL.md`).
3. Write the HTML file to `.transactoid/reports/report-weekly-latest.html` using `execute_shell_command`.
