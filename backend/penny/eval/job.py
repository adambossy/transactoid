"""The eval job: one unattended run (every 12h).

Cohort (ingested since the last watermark) -> branch off prod -> replay the agent
on the branch -> record durable eval rows to prod -> dump the branch to a SQLite
fixture in R2 -> delete the branch -> email the report iff there are
legacy!=agent disagreements. Nothing waits on a human; right/wrong is read later
from your corrections.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
import os
from typing import Any

from loguru import logger
from sqlalchemy import select

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Category, DerivedTransaction
from penny.adapters.storage.r2 import store_object_in_r2
from penny.eval.branch import EvalBranchError, create_eval_branch, delete_eval_branch
from penny.eval.fixture import build_sqlite_fixture_bytes
from penny.eval.replay import replay_one
from penny.eval.report import disagreements, render_eval_report
from penny.eval.version import version_stamp


def _send_report_email(
    to: list[str], run_at: datetime, n_items: int, n_disagree: int, html_doc: str
) -> None:
    from penny.tools.delivery import _build_email_service

    service = _build_email_service()
    subject = (
        f"Categorizer eval {run_at:%Y-%m-%d %H:%M} — "
        f"{n_disagree}/{n_items} disagreements"
    )
    text = (
        f"Categorizer eval for {run_at:%Y-%m-%d %H:%M}: {n_items} transactions, "
        f"{n_disagree} legacy-vs-agent disagreements. Open the HTML report."
    )
    service.send_report(
        to=to, subject=subject, html_content=html_doc, text_content=text
    )


async def run_eval(
    *,
    limit: int | None = None,
    email_to: list[str] | None = None,
    cohort_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Run one eval.

    ``limit`` caps the daily cohort to the most recent N (for testing).
    ``cohort_ids`` overrides cohort selection with an explicit set (a targeted
    rerun / backtest); in that mode the ingest watermark is left untouched so a
    one-off run can't skip future daily cohorts.
    """
    import penny.db as pdb

    prod_url = os.environ.get("DATABASE_URL", "").strip()
    if not prod_url:
        raise RuntimeError("DATABASE_URL is required for the eval job")
    prod = DB(prod_url)
    prod.create_schema()  # idempotent: ensure the eval_* tables exist
    run_at = datetime.now()

    explicit_cohort = cohort_ids is not None
    if explicit_cohort:
        cohort_ids = list(cohort_ids or [])
    else:
        since = prod.last_eval_watermark()
        cohort_ids = prod.derived_ids_created_since(since)
        if limit is not None:
            cohort_ids = cohort_ids[-limit:]
    if not cohort_ids:
        prod.record_eval_run(run_at=run_at, status="skipped_empty", cohort_size=0)
        logger.info("eval: empty cohort; skipped")
        return {"status": "skipped_empty", "cohort_size": 0}

    # A targeted rerun must not advance the daily watermark.
    watermark = None if explicit_cohort else prod.max_created_at_for_ids(cohort_ids)
    branch_name = f"eval-{run_at:%Y%m%dT%H%M%S}"
    logger.info("eval: cohort={} -> branch {}", len(cohort_ids), branch_name)
    branch_id, branch_url = create_eval_branch(branch_name)
    branch = DB(branch_url)
    items: list[dict[str, Any]] = []
    try:
        with branch.session() as session:
            rows = session.execute(
                select(
                    DerivedTransaction.transaction_id,
                    DerivedTransaction.merchant_descriptor,
                    DerivedTransaction.amount_cents,
                    DerivedTransaction.posted_at,
                    Category.key,
                )
                .select_from(DerivedTransaction)
                .outerjoin(
                    Category, Category.category_id == DerivedTransaction.category_id
                )
                .where(DerivedTransaction.transaction_id.in_(cohort_ids))
            ).all()
        base = {
            r[0]: {
                "merchant_descriptor": r[1],
                "amount": (r[2] / 100.0) if r[2] is not None else None,
                "date": r[3].isoformat() if r[3] else None,
                "legacy_key": r[4],
            }
            for r in rows
        }

        # Replay the agent on the branch (point the global DB at it so the agent's
        # tools + prompt history read the frozen branch state, not prod).
        saved_db = pdb._db
        pdb._db = branch
        try:
            for tid in cohort_ids:
                meta = base.get(tid, {})
                txn = {
                    "transaction_id": tid,
                    "merchant_descriptor": meta.get("merchant_descriptor"),
                    "amount": meta.get("amount"),
                    "date": meta.get("date"),
                }
                decision = await replay_one(txn)
                items.append({**txn, "legacy_key": meta.get("legacy_key"), **decision})
        finally:
            pdb._db = saved_db

        run_id = prod.record_eval_run(
            run_at=run_at,
            status="completed",
            cohort_size=len(cohort_ids),
            cohort_max_created_at=watermark,
            branch_name=branch_name,
            version=version_stamp(),
        )
        prod.record_eval_items(run_id, items)

        # Dump the branch to R2 for backtests. Best-effort: the eval rows are the
        # measurement of record; a failed upload must not lose the run.
        r2_key: str | None = f"eval-fixtures/{branch_name}.sqlite.gz"
        try:
            blob = build_sqlite_fixture_bytes(branch)
            store_object_in_r2(
                key=r2_key,
                body=blob,
                content_type="application/gzip",
                metadata={"eval_run_id": str(run_id), "branch": branch_name},
            )
            prod.set_eval_run_fixture(run_id, r2_key)
        except Exception as exc:  # noqa: BLE001 - fixture is non-critical
            logger.warning("eval: R2 fixture upload failed (run kept): {}", exc)
            r2_key = None

        disagree = disagreements(items)
        emailed = False
        if disagree and email_to:
            html_doc = render_eval_report(
                items,
                run_at=run_at.isoformat(timespec="seconds"),
                version=version_stamp(),
            )
            _send_report_email(email_to, run_at, len(items), len(disagree), html_doc)
            emailed = True
        logger.info(
            "eval: completed run {} ({} items, {} disagreements, emailed={})",
            run_id,
            len(items),
            len(disagree),
            emailed,
        )
        return {
            "status": "completed",
            "eval_run_id": run_id,
            "cohort_size": len(cohort_ids),
            "disagreements": len(disagree),
            "branch": branch_name,
            "r2_key": r2_key,
            "emailed": emailed,
        }
    finally:
        with contextlib.suppress(EvalBranchError):
            delete_eval_branch(branch_id)
            logger.info("eval: deleted branch {}", branch_name)
