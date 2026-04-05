# Merchant Rules

These rules map specific merchant descriptors to categories. When a transaction
matches a rule, use the specified category with high confidence and mark it as
rule-matched.

---

## Rule: Costco Gas

**Category:** `transportation_and_auto.fuel`

Costco gas station purchases. Look for descriptors containing "COSTCO GAS",
"COSTCO FUEL", or "COSTCO GASOLINE". These should be categorized as Fuel,
not Groceries (which is where general Costco purchases go).

---

## Rule: Amazon Prime Subscription

**Category:** `entertainment_and_subscriptions.streaming_video`

Amazon Prime subscription charges. Look for descriptors like "AMZN PRIME",
"AMAZON PRIME*", or "Prime Video". These are recurring subscription fees
for the streaming service, not general Amazon purchases.

---

## Rule: Venmo Transfers

**Category:** `banking_movements_transfers_refunds_and_fees.transfer_external_p2p`

Venmo peer-to-peer transfers. Any descriptor containing "VENMO" should be
categorized as external P2P transfer unless context clearly indicates otherwise.

---

## Rule: Julia (Nanny Payment — ATM Withdrawal)

**Category:** `childcare.care`

ATM cash withdrawals used to pay Julia, our nanny. Match transactions where:
- The descriptor indicates an ATM withdrawal (e.g., contains "ATM", "CASH WITHDRAWAL", or similar)
- The amount is between $1,040.00 and $1,070.00

The withdrawal may originate from the ATM at 896 Manhattan Ave, but is not limited to that location. Any ATM withdrawal in this dollar range should be categorized as a nanny/childcare payment.

---
