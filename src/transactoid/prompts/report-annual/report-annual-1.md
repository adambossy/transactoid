# Annual Spending Report

Generate a comprehensive spending report for {{CURRENT_YEAR}}.

## Your Budget Targets

These are my annual budget targets by category (derived from monthly targets):

- **Housing**: $30,000/year (rent, utilities, maintenance)
- **Food**: $9,600/year total
  - Groceries: $6,000/year
  - Restaurants/Dining: $3,600/year
- **Transportation**: $4,800/year (gas, parking, transit, rideshare)
- **Health & Fitness**: $2,400/year (gym, supplements, medical)
- **Entertainment**: $1,800/year (streaming, movies, games)
- **Shopping**: $2,400/year (clothing, electronics, household)
- **Personal Care**: $1,200/year (haircuts, toiletries)
- **Subscriptions**: $1,200/year (software, memberships)

**Total Annual Budget Target**: $53,400/year

## What I Consider "Unusual"

- Any single transaction over $500 that isn't recurring (rent, car payment, etc.)
- Any merchant I've never transacted with before that has charges over $100
- Any category where spending is 50% or more above the prior year's average
- Duplicate charges from the same merchant on the same day

## My Financial Goals & Priorities

- **Primary goal**: Keep total annual spending under $60,000
- **Savings target**: $12,000/year to savings
- **OK to splurge on**: Quality food and fitness (these improve my health and productivity)
- **Need to cut back on**: Impulse shopping, dining out, and subscription creep
- **Seasonal considerations**: Holiday spending in Nov/Dec, travel in summer months

---

## Report Sections to Generate

Please analyze my transaction data and generate a report with these sections:

### 1. Executive Summary
- Total spending this year vs. last year (amount and % change)
- Top 3 areas of concern (overspending or unusual patterns)
- Top 3 positive trends (good spending habits or savings)
- Am I on track to meet my $60,000/year target?

### 2. Category Spending Breakdown
For each major category:
- Amount spent this year
- Budget target vs. actual (over/under)
- Comparison to prior year
- Flag any category where I'm spending 50%+ above the prior year

### 3. Spending Trends (Year-over-Year and Quarterly)
For each category with significant data:
- **Overspending trend**: Categories where spending has been consistently increasing quarter over quarter
- **Underspending trend**: Categories where I'm spending less than usual (potential savings)
- **Stable trend**: Categories where spending is consistent
- **Seasonal patterns**: How spending varied by quarter (Q1, Q2, Q3, Q4)
- Include specific numbers and percentages

### 4. Unusual or Major Expenses
List any transactions that meet my "unusual" criteria above:
- Transaction date, merchant, amount, category
- Why it's flagged (first-time merchant, unusually high, duplicate, etc.)
- Whether it seems like a one-time expense or something to watch

### 5. Predicted Upcoming Expenses
Based on historical patterns:
- **Recurring annual expenses**: What large annual charges should I expect next year?
- **Seasonal patterns**: Based on prior years, what months tend to have higher spending?
- **Trend-based projections**: If current trends continue, what will next year look like?

### 6. Actionable Recommendations
Be specific and honest:
- **Cut back on**: Specific merchants or categories where I'm overspending
- **Maintain**: Areas where my spending is healthy and aligned with goals
- **OK to splurge**: Where I can afford to spend more without guilt
- **Watch out for**: Potential issues or creeping expenses to monitor
- **Year-ahead planning**: Suggestions for budget adjustments based on this year's data

---

## Output Format

Format the report in clean markdown suitable for email delivery. Use tables for numerical comparisons where appropriate. Include actual dollar amounts, percentages, and specific merchant names. Be direct and honest about overspending - I want actionable insights, not sugar-coated summaries.

---

## After Generating the Report

Once you have produced the markdown report above:

1. Include the full markdown report in your final response.
2. Convert the markdown report to a styled HTML document following the render-report-html skill instructions (consult `src/transactoid/skills/render-report-html/SKILL.md`).
3. Write the HTML file to `.transactoid/reports/report-annual-latest.html` using `execute_shell_command`.
