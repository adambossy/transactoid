"""Verdict derivation (from corrections) + metric aggregation.

Verifies the measurement core:
- an item is ``corrected`` when a manual recat lands after the run, ``confirmed``
  when settled and untouched, ``provisional`` when too new;
- fast-path rows are excluded from accuracy;
- the trend summary computes %corrected / exact / parent / win-rate correctly.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from penny.adapters.db.facade import DB
from penny.adapters.db.models import DerivedTransaction, PlaidTransaction
from penny.eval import metrics


def _create_db(tmp_path: Path) -> DB:
    db = DB(f"sqlite:///{tmp_path / 'test.db'}")
    db.create_schema()
    return db


def _seed_txn(db: DB, external_id: str) -> int:
    with db.session() as session:
        plaid = PlaidTransaction(
            external_id=f"plaid-{external_id}",
            source="PLAID",
            account_id="acct-1",
            item_id=None,
            posted_at=date(2026, 1, 10),
            amount_cents=5000,
            currency="USD",
        )
        session.add(plaid)
        session.flush()
        txn = DerivedTransaction(
            plaid_transaction_id=plaid.plaid_transaction_id,
            external_id=external_id,
            amount_cents=5000,
            posted_at=date(2026, 1, 10),
            merchant_descriptor=f"M {external_id}",
        )
        session.add(txn)
        session.flush()
        return int(txn.transaction_id)


def _manual_event(db: DB, txn_id: int, to_key: str, created_at: datetime) -> None:
    """Insert a manual recat event (the correction signal)."""
    from penny.adapters.db.models import TransactionCategoryEvent

    with db.session() as session:
        session.add(
            TransactionCategoryEvent(
                transaction_id=txn_id,
                from_category_id=None,
                to_category_id=1,
                from_category_key="x.y",
                to_category_key=to_key,
                method="manual",
                model=None,
                recategorization_reason="fixing it",
                created_at=created_at,
            )
        )


def _run_with_item(
    db: DB, *, run_at: datetime, tid: int, agent_key: str, legacy_key: str, method: str
) -> int:
    run_id = db.record_eval_run(run_at=run_at, status="completed", cohort_size=1)
    db.record_eval_items(
        run_id,
        [
            {
                "transaction_id": tid,
                "legacy_key": legacy_key,
                "agent_key": agent_key,
                "method_at_eval_time": method,
            }
        ],
    )
    return run_id


def test_corrected_when_manual_recat_after_run(tmp_path: Path) -> None:
    db = _create_db(tmp_path)
    tid = _seed_txn(db, "a")
    _run_with_item(
        db,
        run_at=datetime(2026, 6, 1, 0, 0),
        tid=tid,
        agent_key="food.groceries",
        legacy_key="food.restaurants",
        method="agent",
    )
    # You recategorize it the next day -> the agent was wrong.
    _manual_event(db, tid, "shopping.general", datetime(2026, 6, 2, 0, 0))

    rows = db.eval_items_with_verdicts(settled_before=datetime(2026, 6, 30))
    assert len(rows) == 1
    assert rows[0]["verdict"] == "corrected"
    assert rows[0]["human_key"] == "shopping.general"


def test_confirmed_when_settled_and_untouched(tmp_path: Path) -> None:
    db = _create_db(tmp_path)
    tid = _seed_txn(db, "a")
    _run_with_item(
        db,
        run_at=datetime(2026, 6, 1, 0, 0),
        tid=tid,
        agent_key="food.groceries",
        legacy_key="food.groceries",
        method="agent",
    )
    rows = db.eval_items_with_verdicts(settled_before=datetime(2026, 6, 30))
    assert rows[0]["verdict"] == "confirmed"
    assert rows[0]["human_key"] == "food.groceries"


def test_provisional_when_too_new(tmp_path: Path) -> None:
    db = _create_db(tmp_path)
    tid = _seed_txn(db, "a")
    _run_with_item(
        db,
        run_at=datetime(2026, 6, 28, 0, 0),
        tid=tid,
        agent_key="food.groceries",
        legacy_key="food.groceries",
        method="agent",
    )
    # Settling cutoff is before the run -> still provisional.
    rows = db.eval_items_with_verdicts(settled_before=datetime(2026, 6, 20))
    assert rows[0]["verdict"] == "provisional"
    assert rows[0]["human_key"] is None


def test_metrics_summary_and_fast_path_excluded(tmp_path: Path) -> None:
    db = _create_db(tmp_path)
    # 1) agent correct, disagreed with legacy, confirmed -> agent wins
    t1 = _seed_txn(db, "1")
    _run_with_item(
        db,
        run_at=datetime(2026, 6, 1),
        tid=t1,
        agent_key="food.groceries",
        legacy_key="food.restaurants",
        method="agent",
    )
    # 2) agent wrong -> corrected to a key matching legacy (legacy wins)
    t2 = _seed_txn(db, "2")
    _run_with_item(
        db,
        run_at=datetime(2026, 6, 1),
        tid=t2,
        agent_key="food.groceries",
        legacy_key="shopping.general",
        method="agent",
    )
    _manual_event(db, t2, "shopping.general", datetime(2026, 6, 5))
    # 3) fast-path row -> must be excluded from accuracy
    t3 = _seed_txn(db, "3")
    _run_with_item(
        db,
        run_at=datetime(2026, 6, 1),
        tid=t3,
        agent_key="food.groceries",
        legacy_key="food.groceries",
        method="fast_path",
    )

    items = db.eval_items_with_verdicts(settled_before=datetime(2026, 6, 30))
    summary = metrics.summarize(items)
    assert summary["reviewed"] == 2  # fast-path excluded
    assert summary["corrected"] == 1
    assert summary["pct_corrected"] == 0.5
    assert summary["pct_correct_exact"] == 0.5  # only item 1 exact-matches
    assert summary["legacy_wins"] == 1  # item 2: human==legacy, !=agent
    assert summary["agent_wins"] == 1  # item 1: human==agent, but ==legacy too? no
    assert summary["fast_path"] == 1

    trend = metrics.daily_trend(items)
    assert len(trend) == 1
    assert trend[0]["date"] == "2026-06-01"
    assert trend[0]["reviewed"] == 2
