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

## Rule: Zelle Mortgage Payment
- **Category:** `banking_movements_transfers_refunds_and_fees.transfer_external_p2p`
- **Patterns:** `ZELLE`, `Zelle payment`, `ZELLE TO`, `ZELLE FROM`
- **Description:** Zelle P2P transfers used for mortgage payments; categorized as external transfers to exclude from spending analysis

## Rule: Tameka Childcare
- **Category:** `education_and_childcare.childcare_and_babysitting`
- **Patterns:** `Zelle Payment TO TAMEKA`
- **Description:** Recurring childcare payments via Zelle to Tameka

## Rule: Jubilee Market
- **Category:** `food_and_dining.groceries`
- **Patterns:** `JUBILEE MARKET`, `JUBILEE MARKE`
- **Description:** Jubilee Market grocery purchases
