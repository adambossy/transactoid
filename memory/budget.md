# Budget Memory

This file stores persistent budgeting context that may be useful for budget-oriented
questions. It is optional memory and is not auto-injected into the system prompt.
The agent should read this file only when budget context is relevant.

## Conventions

- Keep entries concise and high signal.
- Use explicit amounts, periods, and category scope.
- Record effective dates when rules change.

## Template

```md
## Budget: <name>
- Amount: <$amount>
- Period: <monthly|weekly|custom>
- Scope: <categories or merchant groups>
- Effective date: <YYYY-MM-DD>
- Notes: <optional rationale>
```

## Example

## Budget: Dining Out
- Amount: $500
- Period: monthly
- Scope: Restaurants and delivery
- Effective date: 2026-02-01
- Notes: Prioritize reducing takeout frequency.
