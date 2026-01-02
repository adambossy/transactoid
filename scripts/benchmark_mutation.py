#!/usr/bin/env python3
"""Benchmark script for measuring mutation phase performance."""

from __future__ import annotations

from pathlib import Path
import time

from transactoid.adapters.amazon import (
    AmazonItemsCSVLoader,
    AmazonOrdersCSVLoader,
    OrderAmountIndex,
)
from transactoid.adapters.db.facade import DB


def benchmark_mutation(db_url: str, limit: int = 100) -> dict[str, float]:
    """Benchmark the mutation phase with timing breakdown.

    Args:
        db_url: Database URL
        limit: Number of plaid_ids to process

    Returns:
        Dict with timing metrics in milliseconds
    """
    db = DB(db_url)

    # Get plaid_ids to process
    with db.session() as session:
        from transactoid.adapters.db.models import PlaidTransaction

        plaid_txns = session.query(PlaidTransaction).limit(limit).all()
        plaid_ids = [txn.plaid_transaction_id for txn in plaid_txns]
        for txn in plaid_txns:
            session.expunge(txn)

    if not plaid_ids:
        print("No plaid transactions found in database")
        return {}

    print(f"Benchmarking with {len(plaid_ids)} plaid_ids...")

    # Load Amazon data once
    csv_dir = Path(".transactions/amazon")
    orders_csv = csv_dir / "amazon-order-history-orders.csv"
    items_csv = csv_dir / "amazon-order-history-items.csv"

    start = time.monotonic()
    amazon_orders = AmazonOrdersCSVLoader(orders_csv).load()
    amazon_items = AmazonItemsCSVLoader(items_csv).load()
    order_index = OrderAmountIndex(amazon_orders)
    csv_load_ms = (time.monotonic() - start) * 1000

    # Benchmark individual DB reads
    db_read_total_ms = 0.0
    amazon_reconcile_ms = 0.0
    amazon_count = 0

    from transactoid.adapters.amazon import (
        create_split_derived_transactions,
        is_amazon_transaction,
    )

    for plaid_id in plaid_ids:
        # Time DB reads
        start = time.monotonic()
        plaid_txn = db.get_plaid_transaction(plaid_id)
        _ = db.get_derived_by_plaid_id(plaid_id)  # Benchmark includes this read
        db_read_total_ms += (time.monotonic() - start) * 1000

        if plaid_txn and is_amazon_transaction(plaid_txn.merchant_descriptor):
            amazon_count += 1
            start = time.monotonic()
            _ = create_split_derived_transactions(plaid_txn, order_index, amazon_items)
            amazon_reconcile_ms += (time.monotonic() - start) * 1000

    db_read_avg = db_read_total_ms / len(plaid_ids) if plaid_ids else 0
    reconcile_avg = amazon_reconcile_ms / amazon_count if amazon_count else 0
    metrics = {
        "plaid_ids_processed": len(plaid_ids),
        "amazon_transactions": amazon_count,
        "csv_load_ms": csv_load_ms,
        "db_read_total_ms": db_read_total_ms,
        "db_read_avg_ms": db_read_avg,
        "amazon_reconcile_total_ms": amazon_reconcile_ms,
        "amazon_reconcile_avg_ms": reconcile_avg,
    }

    print("\n=== Mutation Benchmark Results ===")
    print(f"Plaid IDs processed: {metrics['plaid_ids_processed']}")
    print(f"Amazon transactions: {metrics['amazon_transactions']}")
    print(f"CSV load time: {metrics['csv_load_ms']:.1f}ms")
    print(f"DB reads total: {metrics['db_read_total_ms']:.1f}ms")
    print(f"DB reads avg: {metrics['db_read_avg_ms']:.2f}ms per transaction")
    print(f"Amazon reconcile total: {metrics['amazon_reconcile_total_ms']:.1f}ms")
    avg_ms = metrics["amazon_reconcile_avg_ms"]
    print(f"Amazon reconcile avg: {avg_ms:.2f}ms per Amazon txn")

    return metrics


if __name__ == "__main__":
    import sys

    db_url = sys.argv[1] if len(sys.argv) > 1 else "postgresql://localhost/transactoid"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 250

    benchmark_mutation(db_url, limit)
