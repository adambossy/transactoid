"""Plaid transaction fixtures for matching tests.

These are real transactions from Plaid API exports used to validate
the matching algorithm against Amazon orders.
"""

from datetime import date

from transactoid.adapters.db.models import PlaidTransaction


def create_plaid_transactions() -> list[PlaidTransaction]:
    """Create fixture list of 25 Plaid transactions for matching tests.

    These transactions correspond to the Amazon orders in amazon_orders.py.
    Note: These are detached instances (not bound to a database session).

    Returns:
        List of PlaidTransaction instances in reverse chronological order.
    """
    return [
        # Matches Order 1: 113-5524816-2451403 ($150.25)
        PlaidTransaction(
            plaid_transaction_id=839,
            external_id="om7ddd9XoKHEZ6jaPyKDid4jmpqgvzCr66pea",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 30),
            amount_cents=15025,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 2: 112-5793878-2607402 ($39.27)
        PlaidTransaction(
            plaid_transaction_id=830,
            external_id="3JPDDDgb9phP6Ajd7V8ZIbRqo0zR07C7jdJx9",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 29),
            amount_cents=3927,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 3: 113-2183381-7505026 ($49.77)
        PlaidTransaction(
            plaid_transaction_id=841,
            external_id="gnxYYYp7dLcvK8B5VyLoHaJNv7M4gDf655Bwq",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 30),
            amount_cents=4977,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 4: 113-5891569-5979439 ($28.30)
        PlaidTransaction(
            plaid_transaction_id=825,
            external_id="q3V666aEZATMDd4wzgQ6HvkOYbXnEeHrK4OOv",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 28),
            amount_cents=2830,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 5: 113-0845620-0483424 ($87.09)
        PlaidTransaction(
            plaid_transaction_id=826,
            external_id="BnJaaa6d1zcJ3L84VpqEH4ngo8Be9VHjK5MMg",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 28),
            amount_cents=8709,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 6: 112-7570534-9890666 ($7.61)
        PlaidTransaction(
            plaid_transaction_id=831,
            external_id="yrdyyymqAJTMXBAEQDJZCX59ZML5M7C3nY7Mm",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 29),
            amount_cents=761,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 7: 113-5622584-5484267 ($10.88)
        PlaidTransaction(
            plaid_transaction_id=797,
            external_id="om7ddd9XoKHEZ6jaPyKjUbJy1YXw5XIodgwer",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 23),
            amount_cents=1088,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 8: 112-4502156-7842663 ($40.47)
        PlaidTransaction(
            plaid_transaction_id=771,
            external_id="NKEOOOqk1zsK7JrYoj4PCJwdndOJYeCyMr56J",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 20),
            amount_cents=4047,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 9: 113-5851169-0722617 ($38.21)
        PlaidTransaction(
            plaid_transaction_id=779,
            external_id="om7ddd9XoKHEZ6jaPyK8T078D3nvy9Fr1nPnk",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 21),
            amount_cents=3821,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 10: 113-6936344-4293026 ($8.28)
        PlaidTransaction(
            plaid_transaction_id=778,
            external_id="5ZBPPPjO9phBD0L9MKrNuEMRbgAyJQFNE7K7b",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 21),
            amount_cents=828,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 11: 113-8425491-4935405 ($45.30)
        PlaidTransaction(
            plaid_transaction_id=791,
            external_id="aVvYYYP0yzsBoq64zXZ9CYQayR5Ko6s7aJKL0",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 22),
            amount_cents=4530,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 12: 113-3375353-9086669 ($28.27)
        PlaidTransaction(
            plaid_transaction_id=742,
            external_id="BnJaaa6d1zcJ3L84VpqrHoMYQa9kertvAANeP",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 17),
            amount_cents=2827,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 13: 113-4246085-4890616 ($29.97)
        PlaidTransaction(
            plaid_transaction_id=743,
            external_id="3JPDDDgb9phP6Ajd7V8ps8pYRMAVB7FP99Lmn",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 17),
            amount_cents=2997,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 14: 112-3110699-5201836 ($9.19)
        PlaidTransaction(
            plaid_transaction_id=727,
            external_id="DwZJJJE6KzUwNOk0mZbRUjOX7ZkAZNtqYnQx6",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 16),
            amount_cents=919,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 15: 112-8580438-6561817 ($14.34)
        PlaidTransaction(
            plaid_transaction_id=643,
            external_id="9gkyyydenpTkja981KQ3sDpdpAb9XXUowNo6D",
            source="PLAID",
            account_id="9gkyyydenpTkja981KQgiwE9yeeXYgc6gwOpZ",
            posted_at=date(2025, 12, 6),
            amount_cents=1434,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 16: 112-6047621-2461033 ($6.52)
        PlaidTransaction(
            plaid_transaction_id=606,
            external_id="R0pYYYmdMzSpY8PLwmDbtjxMXJ3Ob5F9Nj5Db",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 12, 2),
            amount_cents=652,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 17: 112-9348880-7178650 ($49.98)
        PlaidTransaction(
            plaid_transaction_id=27,
            external_id="om7ddd9XoKHEZ6jaPyDvSL57ojZYb9U4K5Oj1",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 11, 23),
            amount_cents=4998,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 18: 112-2711996-7841038 ($18.94)
        PlaidTransaction(
            plaid_transaction_id=89,
            external_id="7oyBBBD4ZeUyVrE3LDZpi5QzNnv1ODh0prYyo",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 11, 12),
            amount_cents=1894,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 19: 113-1180294-0059432 ($75.90)
        PlaidTransaction(
            plaid_transaction_id=98,
            external_id="pB9wwwP7OksMZ6rP9R1AixqbzaEVw6U3yrav7",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 11, 12),
            amount_cents=7590,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 20: 112-8565765-9771446 ($48.93)
        PlaidTransaction(
            plaid_transaction_id=148,
            external_id="m1bYYYP7X3cObvJVL86ycnXAaPzoxrCB9YNXJ",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 11, 2),
            amount_cents=4893,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 21: 112-9508317-5020242 ($10.98)
        PlaidTransaction(
            plaid_transaction_id=189,
            external_id="nPgYYYa7ZyhMwNnOxVLriv9RMArroACp09ZPA",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 10, 27),
            amount_cents=1098,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 22: 112-9053665-8377064 ($59.24)
        PlaidTransaction(
            plaid_transaction_id=198,
            external_id="w0nBBB71xaSMDngm36kviJVAPovvmofvybNn3",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 10, 25),
            amount_cents=5924,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 23: 112-5097650-2529056 ($46.51)
        PlaidTransaction(
            plaid_transaction_id=204,
            external_id="q3V666aEZATMDd4wzgP1ixnZ9JAAwJUEBMpy8",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 10, 24),
            amount_cents=4651,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 24: 113-1031800-1734626 ($8.69)
        PlaidTransaction(
            plaid_transaction_id=203,
            external_id="PAQYYYxvMzTAYn3wD460caKZLAmmPAuA16PYg",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 10, 24),
            amount_cents=869,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
        # Matches Order 25: 113-3910520-0532212 ($207.92)
        PlaidTransaction(
            plaid_transaction_id=202,
            external_id="1aD666AR9pIDdKnzvoxahyrveXoo0XcgjZNd8",
            source="PLAID",
            account_id="VaLYYY0DbzIaE59qbMBJSD7yZwwv08Hn4Ey7m",
            posted_at=date(2025, 10, 24),
            amount_cents=20792,
            currency="USD",
            merchant_descriptor="Amazon",
            institution=None,
        ),
    ]
