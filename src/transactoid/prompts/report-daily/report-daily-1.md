# Daily Spending Report

Generate a focused daily spending report for {{CURRENT_DATE}}.

## Your Budget Targets

These are my daily budget targets by category (derived from monthly targets):

- **Housing**: $82/day (rent, utilities, maintenance)
- **Food**: $26/day total
  - Groceries: $16/day
  - Restaurants/Dining: $10/day
- **Transportation**: $13/day (gas, parking, transit, rideshare)
- **Health & Fitness**: $7/day (gym, supplements, medical)
- **Entertainment**: $5/day (streaming, movies, games)
- **Shopping**: $7/day (clothing, electronics, household)
- **Personal Care**: $3/day (haircuts, toiletries)
- **Subscriptions**: $3/day (software, memberships)

**Total Daily Budget Target**: $146/day

## What I Consider "Unusual"

- Any single transaction over $200 that isn't recurring
- Any first-time merchant charge over $75
- Any category where today's spend is 2x or more than the trailing 14-day daily average
- Duplicate charges from the same merchant on the same day

## My Financial Goals & Priorities

- **Primary goal**: Keep daily spending on pace for <$5,000/month
- **Savings target**: Maintain pace for $1,000/month savings
- **OK to splurge on**: Quality food and fitness
- **Need to cut back on**: Impulse shopping, dining out, and subscription creep

---

## Report Sections to Generate

Please analyze my transaction data and generate a report with these sections:

### 1. Executive Summary
- Total spent today vs. yesterday (amount and % change)
- Whether I'm ahead/behind daily budget pace
- Top 2 positive signals
- Top 2 risks to watch tomorrow

### 2. Category Spending Breakdown
For each major category with activity:
- Amount spent today
- Daily budget target vs. actual (over/under)
- Comparison to trailing 14-day daily average
- Flag categories with outsized daily spikes

### 3. Short-Term Trend Context (7 and 14 days)
For meaningful categories:
- Direction of spend trend (up/down/stable)
- How today's amount compares to recent baseline
- Any behavior shift that needs immediate correction

### 4. Unusual or Major Expenses
List transactions that match "unusual" criteria:
- Date/time, merchant, amount, category
- Why it was flagged
- One-time vs. likely recurring concern

### 5. Next 3-Day Outlook
Based on recurring patterns:
- Subscriptions/bills likely due in next 3 days
- High-probability spending categories for next 3 days
- Any expected near-term large expense

### 6. Actionable Recommendations
Be specific and practical:
- **Cut back on**
- **Maintain**
- **Green light**
- **Watch out for tomorrow**

---

## Output Format

Format the report in clean markdown suitable for email delivery. Use tables where helpful. Include specific amounts, percentages, and merchant names. Keep tone direct and action-oriented.

---

## After Generating the Report

Once you have produced the markdown report above:

1. Include the full markdown report in your final response.
2. Convert the markdown report to a styled HTML document following the render-report-html skill instructions (consult `src/transactoid/skills/render-report-html/SKILL.md`).
3. Write the HTML file to `.transactoid/reports/report-daily-latest.html` using `execute_shell_command`.
