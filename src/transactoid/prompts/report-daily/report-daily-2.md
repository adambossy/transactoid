# Daily Spending Report

Generate a focused daily spending report for {{CURRENT_DATE}}.

## Required Sections

Use this exact section order.

### 1. Yesterday at a Glance
- Total spending yesterday (single dollar amount).
- Transaction count yesterday.

### 2. Yesterday Transactions + Category Context
Provide a table with one row per yesterday transaction including:
- Date
- Merchant
- Amount
- Category
- Running category spend "right now" (month-to-date spend for that category as of report time)

### 3. Actionable Recommendations
Provide 3-5 short, concrete actions based on the data.

### 4. Rolling Totals (7 and 14 days)
- Total spending for the last 7 days.
- Total spending for the last 14 days.

### 5. Prior-Month Comparison Windows
For each current window, show the same-length window one month earlier:
- Last 7 days total vs. the equivalent 7-day window one month earlier.
- Last 14 days total vs. the equivalent 14-day window one month earlier.

### 6. Sliding Monthly Projection (15 days back to 15 days forward)
Use a 30-day centered sliding window:
- Historical portion: 15 days prior through today.
- Projection portion: tomorrow through 15 days ahead.
- Provide projected total spending for that full 30-day window and explain the projection basis briefly.

### 7. Category-Level 7/14-Day + Sliding Projection
For each category with activity, provide:
- Last 7-day spend
- Last 14-day spend
- Projected category spend for the same 30-day centered sliding window

## Output Rules
- Output markdown only.
- Use clear tables for sections 2 and 7.
- Include exact dollar amounts.
- Keep tone direct and concise.
