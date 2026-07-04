"""Stage 1 — reconcile prod's alembic baseline + apply the EXPAND half.

Prod is historically ``create_all``-managed with (once) divergent legacy alembic
heads, so a bare ``upgrade head`` is unsafe. This stage:

1. Inspects the recorded alembic state (``alembic current``).
2. If the tenancy chain has NOT started (no ``households`` table), stamps the
   pre-tenancy baseline (``009``) as applied — prod's ``create_all`` schema
   already matches the models at that revision. ``alembic stamp`` also *collapses
   any legacy multi-head* record to the single stamped revision (the repo folds
   the historical divergence at revision 008, so no ``alembic merge`` file is
   manufactured here — stamping the single baseline is the reconciliation).
3. Applies the EXPAND half only: ``alembic upgrade 013`` — identity tables (010),
   ``plaid_accounts`` (011), nullable tenant columns (012), and the dev-only
   backfill (013, a **prod no-op** because ``PENNY_DEV_BACKFILL`` is unset).

Legacy rows still have NULL tenant columns after this — expected. The
interactive assignment + reparent fill them before the contract half lands.

Idempotent: if ``households`` already exists the stamp is skipped and the
``upgrade 013`` is a no-op.
"""

from __future__ import annotations

from common import (
    BASELINE_REVISION,
    EXPAND_HEAD,
    CutoverState,
    alembic_heads,
    alembic_stamp,
    echo,
    make_engine,
    resolve_db_url,
    run_alembic,
    table_exists,
)

STAGE = "reconcile-expand"


def run(*, db_url: str | None, stamp_baseline: str | None, state_file: str, dry_run: bool) -> None:
    url = resolve_db_url(db_url)
    state = CutoverState.load(state_file)
    baseline = stamp_baseline or BASELINE_REVISION

    echo("Current alembic state:")
    echo("  " + (alembic_heads(url) or "(none recorded)"))

    engine = make_engine(url)
    with engine.connect() as conn:
        tenancy_started = table_exists(conn, "households")

    if tenancy_started:
        echo("`households` already present — tenancy chain started; skipping the baseline stamp.")
    else:
        echo(f"Fresh baseline: stamping {baseline!r} (collapses any legacy multi-head record).")
        alembic_stamp(url, baseline, dry_run=dry_run)

    # Expand half only. 013 is a prod no-op (PENNY_DEV_BACKFILL not set here).
    run_alembic(url, EXPAND_HEAD, dry_run=dry_run)

    if not dry_run:
        state.mark_done(STAGE)
        echo(f"Expand half applied through {EXPAND_HEAD}. Legacy tenant columns are NULL (expected).")
