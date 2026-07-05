"""Stage 3 — interactively assign each linked account's owner + visibility.

Lists every linked account (institution, id, a few recent transactions for
recognition) and prompts **owner** (you/spouse) and **visibility**
(private/shared). Each answer is appended to the mapping record file the moment
it is made, so an interrupted run resumes rather than re-prompting. Amazon login
profiles (a separate ownership axis) and the legacy-conversation default are
prompted the same way when present.

The mapping file (default ``accounts.mapping.yaml``) is the auditable,
re-runnable record reparent consumes. ``--dry-run`` lists the accounts and the
current mapping without prompting or writing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
import typer
import yaml

from common import CutoverState, echo, make_engine, require, resolve_db_url, table_exists

STAGE = "assign-accounts"
_VISIBILITIES = ("private", "shared")


def run(*, db_url: str | None, mapping_file: str, state_file: str, dry_run: bool) -> None:
    url = resolve_db_url(db_url)
    state = CutoverState.load(state_file)
    users = dict(state.get("users", {}))  # email -> user_id
    require(len(users) == 2, "run `bootstrap` first — the two pending users must exist in the state file")
    emails = list(users.keys())

    engine = make_engine(url)
    with engine.connect() as conn:
        accounts = _query_accounts(conn)
        amazon = _query_amazon_profiles(conn)

    mapping = _load_mapping(mapping_file)
    mapping.setdefault("household_id", state.get("household_id"))
    mapping.setdefault("accounts", [])
    assigned = {a["account_id"] for a in mapping["accounts"]}

    if dry_run:
        echo(f"[dry-run] {len(accounts)} linked account(s); {len(assigned)} already in {mapping_file}:")
        for a in accounts:
            mark = "assigned" if a["account_id"] in assigned else "UNASSIGNED"
            echo(f"  [{mark}] {a['institution']} / {a['account_id']} ({a['n']} txns)")
        if amazon:
            echo(f"[dry-run] {len(amazon)} amazon profile(s).")
        return

    # Plaid accounts.
    for a in accounts:
        if a["account_id"] in assigned:
            continue
        _show_account(a)
        owner_email = _prompt_owner(emails)
        visibility = _prompt_visibility()
        mapping["accounts"].append(
            {
                "account_id": a["account_id"],
                "item_id": a["item_id"],
                "institution": a["institution"],
                "owner_email": owner_email,
                "owner_user_id": users[owner_email],
                "visibility": visibility,
            }
        )
        _save_mapping(mapping_file, mapping)  # resume-safe: persist each answer
        echo(f"  -> {owner_email} / {visibility}\n")

    # Amazon login profiles (owner/visibility, separate axis).
    if amazon:
        mapping.setdefault("amazon_profiles", [])
        assigned_p = {p["profile_id"] for p in mapping["amazon_profiles"]}
        for p in amazon:
            if p["profile_id"] in assigned_p:
                continue
            echo(f"Amazon profile {p['profile_id']}: {p['display_name']!r}")
            owner_email = _prompt_owner(emails)
            visibility = _prompt_visibility()
            mapping["amazon_profiles"].append(
                {
                    "profile_id": p["profile_id"],
                    "display_name": p["display_name"],
                    "owner_email": owner_email,
                    "owner_user_id": users[owner_email],
                    "visibility": visibility,
                }
            )
            _save_mapping(mapping_file, mapping)
            echo(f"  -> {owner_email} / {visibility}\n")

    # Legacy conversations (household chat threads) — assign an owner + a session
    # mode; finalize applies it once migration 019 adds the columns.
    if "conversations" not in mapping:
        echo("Legacy conversations (existing chat threads):")
        owner_email = _prompt_owner(emails)
        mode = _prompt_choice("Session mode", ("individual", "joint"))
        mapping["conversations"] = {
            "owner_email": owner_email,
            "owner_user_id": users[owner_email],
            "session_mode": mode,
        }
        _save_mapping(mapping_file, mapping)

    _validate(mapping, users)
    state.mark_done(STAGE)
    echo(f"Assignment complete → {mapping_file}. Validated: every account has an owner + visibility.")


# --------------------------------------------------------------------------- #
# Queries                                                                     #
# --------------------------------------------------------------------------- #


def _query_accounts(conn: sa.Connection) -> list[dict[str, Any]]:
    """Distinct linked accounts + a few recent transactions for recognition."""
    rows = (
        conn.execute(
            sa.text(
                "SELECT account_id, MAX(item_id) AS item_id, MAX(institution) AS institution, "
                "COUNT(*) AS n FROM plaid_transactions GROUP BY account_id ORDER BY n DESC"
            )
        )
        .mappings()
        .all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        samples = conn.execute(
            sa.text(
                "SELECT posted_at, amount_cents, merchant_descriptor FROM plaid_transactions "
                "WHERE account_id = :a ORDER BY posted_at DESC LIMIT 3"
            ),
            {"a": r["account_id"]},
        ).all()
        out.append({**dict(r), "samples": samples})
    return out


def _query_amazon_profiles(conn: sa.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "amazon_login_profiles"):
        return []
    return [
        dict(r)
        for r in conn.execute(
            sa.text("SELECT profile_id, display_name FROM amazon_login_profiles ORDER BY profile_id")
        ).mappings()
    ]


# --------------------------------------------------------------------------- #
# Prompts / display                                                           #
# --------------------------------------------------------------------------- #


def _show_account(a: dict[str, Any]) -> None:
    echo(f"Account {a['account_id']} @ {a['institution']} (item {a['item_id']}, {a['n']} txns)")
    for posted_at, cents, desc in a["samples"]:
        echo(f"    {posted_at}  {cents / 100:>10.2f}  {desc or ''}")


def _prompt_owner(emails: list[str]) -> str:
    return _prompt_choice("Owner", tuple(emails))


def _prompt_visibility() -> str:
    return _prompt_choice("Visibility", _VISIBILITIES)


def _prompt_choice(label: str, options: tuple[str, ...]) -> str:
    for i, opt in enumerate(options, 1):
        echo(f"    {i}) {opt}")
    while True:
        choice = typer.prompt(f"  {label}")
        if choice in options:
            return choice
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        echo(f"    invalid — pick 1-{len(options)} or an exact value")


# --------------------------------------------------------------------------- #
# Mapping file I/O + validation                                               #
# --------------------------------------------------------------------------- #


def _load_mapping(path: str) -> dict[str, Any]:
    p = Path(path)
    if p.exists():
        return yaml.safe_load(p.read_text()) or {}
    return {}


def _save_mapping(path: str, mapping: dict[str, Any]) -> None:
    Path(path).write_text(yaml.safe_dump(mapping, sort_keys=False))


def _validate(mapping: dict[str, Any], users: dict[str, str]) -> None:
    valid_ids = set(users.values())
    for a in mapping.get("accounts", []):
        require(a.get("owner_user_id") in valid_ids, f"account {a['account_id']} owner not a pending user")
        require(a.get("visibility") in _VISIBILITIES, f"account {a['account_id']} visibility invalid")
    for p in mapping.get("amazon_profiles", []):
        require(p.get("owner_user_id") in valid_ids, f"amazon profile {p['profile_id']} owner invalid")
        require(p.get("visibility") in _VISIBILITIES, f"amazon profile {p['profile_id']} visibility invalid")
