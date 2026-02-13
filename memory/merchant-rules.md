# Merchant Categorization Rules

Merchant rules provide explicit mappings from merchant descriptors to taxonomy categories. When a transaction matches a rule, the categorizer uses the specified category with high confidence (≥0.95) and automatically marks it as verified.

## Rule: Costco Groceries
- **Category:** `food_and_dining.groceries`
- **Patterns:** `COSTCO`, `COSTCO WHOLESALE`
- **Description:** Costco warehouse club grocery and household purchases

## Rule: Morgan Stanley Mortgage
- **Category:** `housing_and_utilities.mortgage_payment`
- **Patterns:** `MORGAN STANLEY LOAN PAYMT`, `Automated Payment MORGAN STANLEY`
- **Description:** Recurring mortgage payments from Morgan Stanley brokerage account (negative outflows)
