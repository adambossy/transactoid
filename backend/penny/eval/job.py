"""The eval job: one unattended run (every 12h).

Cohort (ingested since the last watermark) -> branch off prod -> replay the agent
on the branch -> record durable eval rows to prod -> upload the run's artifacts
(report HTML, SQLite fixture, items JSON) to R2 -> delete the branch -> email a
link to the hosted report iff there are legacy!=agent disagreements. Nothing
waits on a human; right/wrong is read later from your corrections.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
import json
import os
from typing import Any

from loguru import logger
from sqlalchemy import select

from penny.adapters.db.facade import DB
from penny.adapters.db.models import Category, DerivedTransaction, PlaidTransaction
from penny.adapters.storage.r2 import public_url_for_key, store_object_in_r2
from penny.eval.branch import EvalBranchError, create_eval_branch, delete_eval_branch
from penny.eval.fixture import build_fixture_bytes
from penny.eval.replay import replay_one
from penny.eval.report import disagreements, render_eval_report
from penny.eval.version import version_stamp


def _send_report_link_email(
    to: list[str], run_at: datetime, n_items: int, n_disagree: int, url: str
) -> bool:
    """Email a link to the R2-hosted report; return whether it went out."""
    from penny.tools.delivery import _build_email_service

    service = _build_email_service()
    when = f"{run_at:%Y-%m-%d %H:%M}"
    subject = f"Categorizer eval {when} — {n_disagree}/{n_items} disagreements"
    text = (
        f"Categorizer eval for {when}: {n_items} transactions, {n_disagree} "
        f"legacy-vs-agent disagreements.\n\nReport: {url}\n"
    )
    html = (
        f"<p>Categorizer eval for {when}: {n_items} transactions, "
        f"{n_disagree} legacy-vs-agent disagreements.</p>"
        f'<p><a href="{url}">Open the report</a></p>'
    )
    result = service.send_report(
        to=to, subject=subject, html_content=html, text_content=text
    )
    return bool(getattr(result, "success", False))


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
                    PlaidTransaction.raw_name,
                )
                .select_from(DerivedTransaction)
                .outerjoin(
                    Category, Category.category_id == DerivedTransaction.category_id
                )
                .outerjoin(
                    PlaidTransaction,
                    PlaidTransaction.plaid_transaction_id
                    == DerivedTransaction.plaid_transaction_id,
                )
                .where(DerivedTransaction.transaction_id.in_(cohort_ids))
            ).all()
        base = {
            r[0]: {
                "merchant_descriptor": r[1],
                "amount": (r[2] / 100.0) if r[2] is not None else None,
                "date": r[3].isoformat() if r[3] else None,
                "legacy_key": r[4],
                "raw_name": r[5],
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
                    "raw_name": meta.get("raw_name"),
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

        disagree = disagreements(items)
        html_doc = render_eval_report(
            items,
            run_at=run_at.isoformat(timespec="seconds"),
            version=version_stamp(),
        )

        # Upload the run's artifacts to R2 under one prefix: the report HTML, the
        # SQLite fixture (for backtests), and the machine-readable items JSON.
        # The fixture + items hold real transaction data, so they go in the
        # private default bucket; only the report is uploaded to the (optional)
        # PUBLIC report bucket so its emailed link can be permanent. Best-effort:
        # a failed upload must not lose the run. r2_fixture_url stores the fixture
        # KEY (backtests download by key); report_url is a shareable link.
        prefix = f"eval-runs/{branch_name}"
        fixture_key = f"{prefix}/fixture.tar.gz"
        report_key = f"{prefix}/report.html"
        report_bucket = os.environ.get("R2_REPORT_BUCKET", "").strip() or None
        meta = {"eval_run_id": str(run_id), "branch": branch_name}
        report_url: str | None = None
        try:
            store_object_in_r2(
                key=fixture_key,
                body=build_fixture_bytes(branch),
                content_type="application/gzip",
                metadata=meta,
            )
            prod.set_eval_run_fixture(run_id, fixture_key)
            store_object_in_r2(
                key=f"{prefix}/items.json",
                body=json.dumps(items, default=str, indent=2).encode("utf-8"),
                content_type="application/json",
                metadata=meta,
            )
            store_object_in_r2(
                key=report_key,
                body=html_doc.encode("utf-8"),
                content_type="text/html; charset=utf-8",
                metadata=meta,
                bucket=report_bucket,
            )
            report_url = public_url_for_key(report_key, bucket=report_bucket)
        except Exception as exc:  # noqa: BLE001 - artifacts are non-critical
            logger.warning("eval: R2 artifact upload failed (run kept): {}", exc)

        emailed = False
        if disagree and email_to and report_url:
            # Best-effort: a bounced email must not fail the eval (rows are kept).
            try:
                emailed = _send_report_link_email(
                    email_to, run_at, len(items), len(disagree), report_url
                )
            except Exception as exc:  # noqa: BLE001 - email is non-critical
                logger.warning("eval: report email failed (run kept): {}", exc)
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
            "fixture_key": fixture_key,
            "report_url": report_url,
            "emailed": emailed,
        }
    finally:
        with contextlib.suppress(EvalBranchError):
            delete_eval_branch(branch_id)
            logger.info("eval: deleted branch {}", branch_name)
