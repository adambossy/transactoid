# Weekly Spending Report

Generate a comprehensive spending report for the week ending {{CURRENT_DATE}}.

## Your Budget Targets

These are my weekly budget targets by category (derived from monthly targets):

- **Housing**: $581/week (rent, utilities, maintenance)
- **Food**: $186/week total
  - Groceries: $116/week
  - Restaurants/Dining: $70/week
- **Transportation**: $93/week (gas, parking, transit, rideshare)
- **Health & Fitness**: $47/week (gym, supplements, medical)
- **Entertainment**: $35/week (streaming, movies, games)
- **Shopping**: $47/week (clothing, electronics, household)
- **Personal Care**: $23/week (haircuts, toiletries)
- **Subscriptions**: $23/week (software, memberships)

**Total Weekly Budget Target**: $1,035/week

## What I Consider "Unusual"

- Any single transaction over $500 that isn't recurring (rent, car payment, etc.)
- Any merchant I've never transacted with before that has charges over $100
- Any category where spending is 50% or more above the 4-week average
- Duplicate charges from the same merchant on the same day

## My Financial Goals & Priorities

- **Primary goal**: Keep total weekly spending under $1,163 ($5,000/month equivalent)
- **Savings target**: $233/week to savings ($1,000/month equivalent)
- **OK to splurge on**: Quality food and fitness (these improve my health and productivity)
- **Need to cut back on**: Impulse shopping, dining out, and subscription creep
- **Seasonal considerations**: Holiday spending in Nov/Dec, travel in summer months

---

## Report Sections to Generate

Please analyze my transaction data and generate a report with these sections:

### 1. Executive Summary
- Total spending this week vs. last week (amount and % change)
- Top 3 areas of concern (overspending or unusual patterns)
- Top 3 positive trends (good spending habits or savings)
- Am I on track to meet my weekly target?

### 2. Category Spending Breakdown
For each major category:
- Amount spent this week
- Budget target vs. actual (over/under)
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
