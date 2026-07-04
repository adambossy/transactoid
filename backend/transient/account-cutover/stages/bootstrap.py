"""Stage 2 — bootstrap the household + two PENDING users.

Creates exactly one ``households`` row and two ``users`` rows with
``external_auth_id = NULL`` — *pending* identities, no Clerk objects, no
passwords. Phase-4 first-login linking later matches each spouse's verified
email to their pending row and claims it (the handoff). This stage is the ONLY
place prod identity is created (migrations never invent it).

Idempotent: the household + users are keyed by the state file and by email, so a
re-run reuses existing ids and skips inserts. UUIDs are typed on the bind so the
same statement works on Postgres (prod/rehearsal) and SQLite (local smoke).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from common import CutoverState, echo, make_engine, require, resolve_db_url

STAGE = "bootstrap"


def _uuid_stmt(sql: str, *names: str) -> sa.TextClause:
    return sa.text(sql).bindparams(*(sa.bindparam(n, type_=sa.Uuid()) for n in names))


def run(*, db_url: str | None, household_name: str, emails: list[str], state_file: str, dry_run: bool) -> None:
    url = resolve_db_url(db_url)
    state = CutoverState.load(state_file)
    require(len(emails) == 2, f"expected exactly 2 --email values (you + spouse), got {len(emails)}")

    household_id = uuid.UUID(state.get("household_id")) if state.get("household_id") else uuid.uuid4()
    users: dict[str, str] = dict(state.get("users", {}))  # email -> user_id (str)
    for email in emails:
        users.setdefault(email, str(uuid.uuid4()))

    if dry_run:
        echo("[dry-run] would ensure identity rows:")
        echo(f"  households: {household_id} name={household_name!r}")
        for email in emails:
            echo(f"  users: {users[email]} email={email!r} external_auth_id=NULL (pending)")
        return

    engine = make_engine(url)
    with engine.begin() as conn:
        exists = conn.execute(
            _uuid_stmt("SELECT 1 FROM households WHERE household_id = :h", "h"),
            {"h": household_id},
        ).first()
        if exists:
            echo(f"Household {household_id} already present — reusing.")
        else:
            conn.execute(
                _uuid_stmt("INSERT INTO households (household_id, name) VALUES (:h, :n)", "h"),
                {"h": household_id, "n": household_name},
            )
            echo(f"Created household {household_id} ({household_name!r}).")

        for email in emails:
            user_id = uuid.UUID(users[email])
            found = conn.execute(
                sa.text("SELECT user_id FROM users WHERE email = :e"), {"e": email}
            ).first()
            if found:
                users[email] = str(found[0])
                echo(f"User {email!r} already present ({found[0]}) — reusing (pending).")
                continue
            conn.execute(
                _uuid_stmt(
                    "INSERT INTO users (user_id, household_id, email, external_auth_id) "
                    "VALUES (:u, :h, :e, NULL)",
                    "u",
                    "h",
                ),
                {"u": user_id, "h": household_id, "e": email},
            )
            echo(f"Created pending user {email!r} ({user_id}); external_auth_id NULL.")

    state.set("household_id", str(household_id))
    state.set("household_name", household_name)
    state.set("users", users)
    state.mark_done(STAGE)
    echo("Bootstrap complete. Phase-4 first-login linking will claim these pending users.")
