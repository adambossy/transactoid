"""Stage 5 — apply the CONTRACT half now that every row is assigned.

``alembic upgrade head`` applies 014→head: NOT NULL + FKs + CHECKs + indexes
(014), RLS USING/WITH CHECK (015), per-household categories (016), token
encryption (017), the workspace store (018), conversation tenancy + web RLS
(019), and the phase-2b billing tables (020/021). These can only land after
reparent because the NOT-NULL/RLS contract requires every legacy row to be
assigned first.

Two env details make the contract apply cleanly on prod:

- ``PENNY_DEV_HOUSEHOLD_ID`` (+ name) is injected so migration 016 backfills
  ``categories.household_id`` to the cutover household before tightening it to
  NOT NULL (categories are household-scoped; there is exactly one household).
- ``PENNY_DEV_BACKFILL`` is deliberately **NOT** set, so migration 013 stays a
  no-op and never overwrites reparent's per-account ownership with a blanket
  user1/private backfill.
- ``PENNY_PLAID_TOKEN_KEY`` must be exported by the operator (017 needs it if
  any token is still plaintext; reparent normally encrypted them already).

After the upgrade, ``web.conversations`` (whose tenant columns migration 019 adds
nullable) is backfilled from the mapping's ``conversations`` section. 019 also
FORCEs RLS, so the backfill briefly disables the policy (as the table owner) to
reach the still-NULL rows, assigns them, then re-enables + FORCEs it. Prod
typically has zero legacy conversations (the store is a new phase-2 feature), in
which case this is a clean no-op.
"""

from __future__ import annotations

from pathlib import Path
import uuid

import sqlalchemy as sa
import yaml

from common import (
    CONTRACT_HEAD,
    CutoverState,
    echo,
    is_postgres,
    make_engine,
    resolve_db_url,
    run_alembic,
    table_exists,
)

STAGE = "finalize-schema"


def run(*, db_url: str | None, mapping_file: str, state_file: str, dry_run: bool) -> None:
    url = resolve_db_url(db_url)
    state = CutoverState.load(state_file)
    household_id = state.get("household_id")

    extra_env: dict[str, str] = {}
    if household_id:
        # Lets migration 016 backfill categories to the cutover household before
        # its NOT NULL. NOTE: PENNY_DEV_BACKFILL is intentionally absent (013
        # stays a no-op — reparent already set per-account ownership).
        extra_env["PENNY_DEV_HOUSEHOLD_ID"] = household_id
        if state.get("household_name"):
            extra_env["PENNY_DEV_HOUSEHOLD_NAME"] = state.get("household_name")

    echo("Applying CONTRACT half (alembic upgrade head) — categories self-backfill via "
         "PENNY_DEV_HOUSEHOLD_ID; PENNY_DEV_BACKFILL intentionally unset.")
    run_alembic(url, CONTRACT_HEAD, dry_run=dry_run, extra_env=extra_env)

    if dry_run:
        echo("[dry-run] would then backfill web.conversations from the mapping (see below).")
        _report_conversations_plan(url, mapping_file, state)
        return

    _backfill_conversations(url, mapping_file, state)
    state.mark_done(STAGE)
    echo("Contract half applied. Schema is now alembic-managed; create_all no longer governs prod.")


def _conversation_target(mapping_file: str, state: CutoverState) -> tuple[str, str]:
    """(owner_user_id, session_mode) for legacy conversations, from the mapping's
    conversations section, falling back to the first pending user / individual."""
    mapping = yaml.safe_load(Path(mapping_file).read_text()) if Path(mapping_file).exists() else {}
    conv = (mapping or {}).get("conversations") or {}
    owner = conv.get("owner_user_id")
    if not owner:
        users = state.get("users", {})
        owner = next(iter(users.values())) if users else None
    return owner, conv.get("session_mode", "individual")


def _report_conversations_plan(url: str, mapping_file: str, state: CutoverState) -> None:
    owner, mode = _conversation_target(mapping_file, state)
    echo(f"[dry-run] web.conversations -> household={state.get('household_id')} "
         f"owner={owner} session_mode={mode} (only rows with NULL household).")


def _backfill_conversations(url: str, mapping_file: str, state: CutoverState) -> None:
    engine = make_engine(url)
    if not is_postgres(engine):
        echo("web.conversations backfill skipped (SQLite dev uses app-layer tenancy).")
        return
    # One transaction for the whole backfill: on the SQLAlchemy 2.0 future engine
    # the first ``conn.execute`` autobegins, so a nested ``conn.begin()`` would
    # raise InvalidRequestError. ``engine.begin()`` gives a single explicit txn
    # that the COUNT, the RLS toggles, and the UPDATE all share and that commits
    # atomically (Postgres DDL is transactional, so the DISABLE/ENABLE pair is
    # rolled back with everything else if the UPDATE fails).
    with engine.begin() as conn:
        if not table_exists(conn, "web.conversations"):
            echo("web.conversations not present — skipping conversation backfill.")
            return
        household_id = state.get("household_id")
        owner, mode = _conversation_target(mapping_file, state)
        pending = conn.execute(
            sa.text("SELECT COUNT(*) FROM web.conversations WHERE household_id IS NULL")
        ).scalar_one()
        if not pending:
            echo("web.conversations: no unassigned rows (clean no-op).")
            return
        echo(f"web.conversations: assigning {pending} legacy thread(s) to household {household_id}.")
        # 019 FORCEs RLS; the still-NULL rows are invisible to a normal UPDATE.
        # Briefly drop the policy as the table owner to reach them, then restore.
        conn.execute(sa.text("ALTER TABLE web.conversations DISABLE ROW LEVEL SECURITY"))
        conn.execute(
            sa.text(
                "UPDATE web.conversations SET household_id = :h, owner_user_id = :u, "
                "session_mode = COALESCE(session_mode, :m) WHERE household_id IS NULL"
            ).bindparams(
                sa.bindparam("h", type_=sa.Uuid()),
                sa.bindparam("u", type_=sa.Uuid()),
            ),
            {"h": uuid.UUID(str(household_id)), "u": uuid.UUID(str(owner)), "m": mode},
        )
        conn.execute(sa.text("ALTER TABLE web.conversations ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text("ALTER TABLE web.conversations FORCE ROW LEVEL SECURITY"))
        echo("web.conversations backfill complete; RLS re-enabled + FORCEd.")
