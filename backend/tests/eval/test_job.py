"""End-to-end eval run on SQLite — no neonctl, no network.

Proves the neonctl-free path: `run_eval` snapshots prod finance data into a local
SQLite copy, replays (stubbed) on it, and records durable rows to prod — with the
global DB restored afterward and no Neon-branch dependency anywhere.
"""

from __future__ import annotations

from datetime import date, datetime
import importlib
from pathlib import Path

import pytest

from penny.adapters.db.facade import DB
from penny.adapters.db.models import (
    Category,
    DerivedTransaction,
    EvalItem,
    EvalRun,
    PlaidTransaction,
)
import penny.db as pdb
from penny.eval.job import run_eval


def _seed_prod(tmp_path: Path) -> str:
    """Seed a SQLite 'prod' DB with one categorizable txn; return its URL."""
    url = f"sqlite:///{tmp_path / 'prod.db'}"
    db = DB(url, enforce_sqlite_fks=True)
    db.create_schema()
    with db.session() as session:
        cat = Category(key="food.groceries", name="Groceries")
        session.add(cat)
        session.flush()
        plaid = PlaidTransaction(
            external_id="p1",
            source="PLAID",
            account_id="acct-1",
            item_id=None,
            posted_at=date(2026, 1, 10),
            amount_cents=5000,
            currency="USD",
            raw_name="WHOLE FOODS #123",
        )
        session.add(plaid)
        session.flush()
        session.add(
            DerivedTransaction(
                plaid_transaction_id=plaid.plaid_transaction_id,
                external_id="d1",
                amount_cents=5000,
                posted_at=date(2026, 1, 10),
                merchant_descriptor="WHOLE FOODS",
                category_id=cat.category_id,
                category_method="llm",
                category_assigned_at=datetime(2026, 1, 10, 12, 0),
            )
        )
    return url


@pytest.fixture
def _stub_replay_and_r2(monkeypatch):
    """Deterministic replay + no-op R2 so the run needs no LLM or network."""

    async def _fake_replay(txn):
        return {
            "method_at_eval_time": "agent",
            "agent_key": "food.dining",  # disagrees with legacy 'food.groceries'
            "agent_confidence": 0.9,
            "agent_reasoning": "stub",
            "tools_consulted": [],
            "trace_link": None,
        }

    monkeypatch.setattr("penny.eval.job.replay_one", _fake_replay)
    monkeypatch.setattr("penny.eval.job.store_object_in_r2", lambda **kw: None)
    monkeypatch.setattr(
        "penny.eval.job.public_url_for_key",
        lambda key, bucket=None: f"https://r2/{key}",
    )


def _point_env_at(monkeypatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PENNY_AGENT_READONLY_DATABASE_URL", url)
    # Bind the singletons to the seeded URL. `_db` is a concrete baseline so the
    # replay's save/restore is observable (a None baseline gets lazily re-created
    # by post-replay get_db() callers, hiding the restore).
    monkeypatch.setattr(pdb, "_db", DB(url, enforce_sqlite_fks=True))
    monkeypatch.setattr(pdb, "_readonly_db", None)


async def test_run_eval_completes_on_sqlite(tmp_path, monkeypatch, _stub_replay_and_r2):
    url = _seed_prod(tmp_path)
    _point_env_at(monkeypatch, url)
    saved_db = pdb._db  # concrete baseline global

    result = await run_eval(email_to=None)

    assert result["status"] == "completed"
    assert result["cohort_size"] == 1
    assert result["disagreements"] == 1
    # The replay's global-DB swap was balanced: the disposable snapshot did not
    # leak into the process-global handle.
    assert pdb._db is saved_db

    # Durable rows landed in prod.
    prod = DB(url, enforce_sqlite_fks=True)
    with prod.session() as session:
        run = session.query(EvalRun).one()
        assert run.status == "completed"
        assert run.cohort_size == 1
        assert run.branch_name and run.branch_name.startswith("eval-")
        assert session.query(EvalItem).count() == 1


async def test_run_eval_skips_empty_cohort(tmp_path, monkeypatch, _stub_replay_and_r2):
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    DB(url, enforce_sqlite_fks=True).create_schema()  # schema, no txns
    _point_env_at(monkeypatch, url)

    result = await run_eval(email_to=None)

    assert result["status"] == "skipped_empty"
    prod = DB(url, enforce_sqlite_fks=True)
    with prod.session() as session:
        assert session.query(EvalRun).one().status == "skipped_empty"


async def test_run_eval_records_failed_and_alerts(tmp_path, monkeypatch):
    """A crash records a durable 'failed' row and sends a failure email, then raises."""
    url = _seed_prod(tmp_path)
    _point_env_at(monkeypatch, url)

    async def _boom(txn):
        raise RuntimeError("replay exploded")

    monkeypatch.setattr("penny.eval.job.replay_one", _boom)
    monkeypatch.setattr("penny.eval.job.store_object_in_r2", lambda **kw: None)
    monkeypatch.setattr(
        "penny.eval.job.public_url_for_key", lambda key, bucket=None: "x"
    )
    sent: list[dict] = []
    monkeypatch.setattr(
        "penny.eval.job._send_status_email",
        lambda to, run_at, **kw: sent.append(kw) or True,
    )

    with pytest.raises(RuntimeError, match="replay exploded"):
        await run_eval(email_to=["me@example.com"])

    # Durable failure record (watermark not advanced, real cohort size) + one alert.
    prod = DB(url, enforce_sqlite_fks=True)
    with prod.session() as session:
        run = session.query(EvalRun).one()
        assert run.status == "failed"
        assert run.cohort_max_created_at is None
        assert run.cohort_size == 1  # selected before the replay crash, not 0
    assert len(sent) == 1 and sent[0]["status"] == "failed"


async def test_snapshot_completeness_guard(tmp_path, monkeypatch, _stub_replay_and_r2):
    """A cohort id absent from the snapshot fails loudly (never a silent drop)."""
    url = _seed_prod(tmp_path)
    _point_env_at(monkeypatch, url)

    # Explicit cohort referencing a transaction the snapshot does not contain.
    with pytest.raises(RuntimeError, match="snapshot missing"):
        await run_eval(email_to=None, cohort_ids=[999])

    # The run is recorded failed, and the watermark never advanced.
    prod = DB(url, enforce_sqlite_fks=True)
    with prod.session() as session:
        assert session.query(EvalRun).one().status == "failed"


async def test_limit_run_does_not_advance_watermark(
    tmp_path, monkeypatch, _stub_replay_and_r2
):
    """A --limit run is a non-committing sample: it never advances the watermark."""
    url = _seed_prod(tmp_path)  # one txn
    _point_env_at(monkeypatch, url)

    result = await run_eval(email_to=None, limit=1)

    assert result["status"] == "completed"
    prod = DB(url, enforce_sqlite_fks=True)
    with prod.session() as session:
        run = session.query(EvalRun).one()
        # watermark stays NULL, so last_eval_watermark() is unaffected and the
        # sampled rows are re-selected by the next real (unlimited) run.
        assert run.cohort_max_created_at is None
    assert prod.last_eval_watermark() is None


async def test_negative_limit_rejected(tmp_path, monkeypatch, _stub_replay_and_r2):
    """A non-positive --limit is rejected, not silently turned into a slice."""
    url = _seed_prod(tmp_path)
    _point_env_at(monkeypatch, url)
    for bad in (-1, 0):
        with pytest.raises(ValueError, match="positive integer"):
            await run_eval(email_to=None, limit=bad)


def test_no_neon_branch_dependency():
    """The eval must carry no neonctl/Neon-branch code."""
    job = importlib.import_module("penny.eval.job")
    assert not hasattr(job, "create_eval_branch")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("penny.eval.branch")
