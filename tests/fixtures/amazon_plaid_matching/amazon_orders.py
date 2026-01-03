"""Amazon order fixtures for matching tests.

These are real orders from Amazon CSV exports used to validate
the matching algorithm against Plaid transactions.
"""

from datetime import date

from transactoid.adapters.amazon.csv_loader import CSVOrder


def create_csv_orders() -> list[CSVOrder]:
    """Create fixture list of 25 Amazon orders for matching tests.

    Returns:
        List of CSVOrder instances in reverse chronological order.
    """
    return [
        CSVOrder(
            order_id="113-5524816-2451403",
            order_date=date(2025, 12, 29),
            order_total_cents=15025,
            tax_cents=1225,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-5793878-2607402",
            order_date=date(2025, 12, 28),
            order_total_cents=3927,
            tax_cents=320,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-2183381-7505026",
            order_date=date(2025, 12, 27),
            order_total_cents=4977,
            tax_cents=161,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-5891569-5979439",
            order_date=date(2025, 12, 27),
            order_total_cents=2830,
            tax_cents=231,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-0845620-0483424",
            order_date=date(2025, 12, 27),
            order_total_cents=8709,
            tax_cents=710,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-7570534-9890666",
            order_date=date(2025, 12, 26),
            order_total_cents=761,
            tax_cents=62,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-5622584-5484267",
            order_date=date(2025, 12, 22),
            order_total_cents=1088,
            tax_cents=89,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-4502156-7842663",
            order_date=date(2025, 12, 20),
            order_total_cents=4047,
            tax_cents=330,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-5851169-0722617",
            order_date=date(2025, 12, 20),
            order_total_cents=3821,
            tax_cents=124,
            shipping_cents=299,
        ),
        CSVOrder(
            order_id="113-6936344-4293026",
            order_date=date(2025, 12, 20),
            order_total_cents=828,
            tax_cents=68,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-8425491-4935405",
            order_date=date(2025, 12, 18),
            order_total_cents=4530,
            tax_cents=133,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-3375353-9086669",
            order_date=date(2025, 12, 16),
            order_total_cents=2827,
            tax_cents=229,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-4246085-4890616",
            order_date=date(2025, 12, 16),
            order_total_cents=2997,
            tax_cents=0,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-3110699-5201836",
            order_date=date(2025, 12, 14),
            order_total_cents=919,
            tax_cents=75,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-8580438-6561817",
            order_date=date(2025, 12, 5),
            order_total_cents=1434,
            tax_cents=117,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-6047621-2461033",
            order_date=date(2025, 12, 1),
            order_total_cents=652,
            tax_cents=53,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-9348880-7178650",
            order_date=date(2025, 11, 22),
            order_total_cents=4998,
            tax_cents=0,
            shipping_cents=299,
        ),
        CSVOrder(
            order_id="112-2711996-7841038",
            order_date=date(2025, 11, 12),
            order_total_cents=1894,
            tax_cents=154,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-1180294-0059432",
            order_date=date(2025, 11, 11),
            order_total_cents=7590,
            tax_cents=399,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-8565765-9771446",
            order_date=date(2025, 11, 2),
            order_total_cents=4893,
            tax_cents=399,
            shipping_cents=299,
        ),
        CSVOrder(
            order_id="112-9508317-5020242",
            order_date=date(2025, 10, 26),
            order_total_cents=1098,
            tax_cents=0,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-9053665-8377064",
            order_date=date(2025, 10, 24),
            order_total_cents=5924,
            tax_cents=483,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="112-5097650-2529056",
            order_date=date(2025, 10, 24),
            order_total_cents=4651,
            tax_cents=379,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-1031800-1734626",
            order_date=date(2025, 10, 24),
            order_total_cents=869,
            tax_cents=71,
            shipping_cents=0,
        ),
        CSVOrder(
            order_id="113-3910520-0532212",
            order_date=date(2025, 10, 23),
            order_total_cents=20792,
            tax_cents=1695,
            shipping_cents=0,
        ),
    ]
