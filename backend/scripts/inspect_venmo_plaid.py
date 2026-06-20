#!/usr/bin/env python3
"""One-off: inspect RAW Plaid fields for Venmo transactions.

Question being answered: our `plaid_transactions.merchant_descriptor` stores
only ``merchant_name or name``, and for Venmo Plaid sets merchant_name="Venmo",
so we persist the bare string "Venmo" and lose any counterparty. Does Plaid
actually carry the counterparty in fields we drop (``name``,
``original_description``, ``payment_meta``, ``counterparties``)?

This script pulls transactions directly from Plaid for every stored item, keeps
only the Venmo ones, and dumps the raw fields so we can verify. It is READ-ONLY
(only calls /transactions/get) and writes nothing to the DB.

Access tokens are read from the plaid_items table (point DATABASE_URL at the
test branch — a copy of prod — via .env.test). Plaid credentials come from the
PLAID_* env vars (production secret). Run:

  set -a && source .env.test && set +a          # DATABASE_URL -> test branch
  eval "$(grep -E '^PLAID_' ~/code/transactoid/.env | sed 's/^/export /')"
  uv run python scripts/inspect_venmo_plaid.py
"""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from penny.adapters.clients.plaid import PlaidClient  # noqa: E402
from penny.adapters.db.models import PlaidItem  # noqa: E402
from penny.db import get_db  # noqa: E402

_LOOKBACK_DAYS = 720
_PAGE = 500
_MAX_SCAN_PER_ITEM = 4000


def _is_venmo(txn: dict[str, Any]) -> bool:
    fields = [
        txn.get("merchant_name") or "",
        txn.get("name") or "",
        txn.get("original_description") or "",
    ]
    return any("venmo" in f.lower() for f in fields)


def _fetch_raw(
    client: PlaidClient, access_token: str, start: date, end: date, offset: int
) -> dict[str, Any]:
    """Call /transactions/get and return the raw response (with paging).

    Goes through the client's POST helper directly only to set the page offset;
    original_description is returned by Plaid by default. Diagnostic-only.
    """
    payload = {
        "client_id": client._client_id,  # noqa: SLF001 - one-off diagnostic
        "secret": client._secret,  # noqa: SLF001
        "access_token": access_token,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "options": {
            "count": _PAGE,
            "offset": offset,
        },
    }
    return client._post("/transactions/get", payload)  # noqa: SLF001


def main() -> int:
    end = date.today()
    start = end - timedelta(days=_LOOKBACK_DAYS)

    with get_db().session() as session:
        items = [
            (it.item_id, it.access_token, it.institution_name)
            for it in session.query(PlaidItem).all()
        ]
    if not items:
        print(
            "No plaid_items found (is DATABASE_URL the test branch?).", file=sys.stderr
        )
        return 2

    client = PlaidClient.from_env()
    print(f">> {len(items)} items; scanning {start} .. {end} for Venmo transactions\n")

    venmo: list[dict[str, Any]] = []
    for item_id, access_token, institution in items:
        scanned = 0
        offset = 0
        while scanned < _MAX_SCAN_PER_ITEM:
            try:
                resp = _fetch_raw(client, access_token, start, end, offset)
            except Exception as exc:  # noqa: BLE001 - diagnostic, keep going
                print(f"   ! item {item_id} ({institution}): {exc}")
                break
            txns = resp.get("transactions", [])
            total = int(resp.get("total_transactions", 0))
            for t in txns:
                if _is_venmo(t):
                    t["_institution"] = institution
                    venmo.append(t)
            scanned += len(txns)
            offset += len(txns)
            if not txns or scanned >= total:
                break

    print(f">> Found {len(venmo)} Venmo transaction(s).\n")
    for t in venmo[:25]:
        print("-" * 72)
        print(f"  institution:          {t.get('_institution')}")
        print(f"  name:                 {t.get('name')!r}")
        print(f"  merchant_name:        {t.get('merchant_name')!r}")
        print(f"  original_description: {t.get('original_description')!r}")
        print(f"  payment_meta:         {json.dumps(t.get('payment_meta'))}")
        print(f"  counterparties:       {json.dumps(t.get('counterparties'))}")
        print(f"  amount:               {t.get('amount')}  date: {t.get('date')}")

    # Verdict: which dropped field, if any, actually carries a counterparty.
    print("\n" + "=" * 72)
    with_name_detail = sum(
        1 for t in venmo if (t.get("name") or "").strip().lower() not in ("", "venmo")
    )
    with_pm = sum(
        1
        for t in venmo
        if (t.get("payment_meta") or {}).get("payee")
        or (t.get("payment_meta") or {}).get("payer")
    )
    with_cp = sum(1 for t in venmo if t.get("counterparties"))
    with_orig = sum(
        1
        for t in venmo
        if (t.get("original_description") or "").strip().lower() not in ("", "venmo")
    )
    print("Counterparty availability across Venmo transactions:")
    print(f"  name has detail beyond 'Venmo':   {with_name_detail}/{len(venmo)}")
    print(f"  original_description has detail:   {with_orig}/{len(venmo)}")
    print(f"  payment_meta.payee/payer present:  {with_pm}/{len(venmo)}")
    print(f"  counterparties[] present:          {with_cp}/{len(venmo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
