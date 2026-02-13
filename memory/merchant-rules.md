# Merchant Categorization Rules

Explicit mappings for specific merchant descriptors. When a transaction matches one of these rules, the categorizer should use the specified category with high confidence (≥0.95) and set `rule_matched=true` with the `rule_name`.

## Rule Format

Each rule follows this structure:

```md
## Rule: <short_name>
- **Category:** `<taxonomy.key>`
- **Patterns:** `<pattern_1>`, `<pattern_2>`, `<pattern_3>`
- **Description:** <one short disambiguating sentence>
```

**Constraints:**
- One category per rule
- Patterns are fuzzy clues for matching merchant descriptors, not exact-only matches
- Category keys must be valid taxonomy keys
- Keep rules compact and high-signal

## Example Rules

## Rule: Costco Gas
- **Category:** `transportation.fuel`
- **Patterns:** `COSTCO GAS`, `COSTCO GASOLINE`
- **Description:** Costco fuel purchases at warehouse gas stations

## Rule: Amazon Fresh
- **Category:** `food.groceries`
- **Patterns:** `AMAZON FRESH`, `AMZN FRESH`, `AMAZON.COM*FRESH`
- **Description:** Amazon Fresh grocery delivery service

## Rule: Whole Foods Market
- **Category:** `food.groceries`
- **Patterns:** `WHOLE FOODS`, `WFM`, `WHOLEFDS`
- **Description:** Whole Foods Market grocery stores
