#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from typing import Any, Dict

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

PLAID_ENV_MAP: Dict[str, str] = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def getenv_or_die(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def plaid_base_url() -> str:
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    base_url = PLAID_ENV_MAP.get(env)
    if not base_url:
        print(
            f"Invalid PLAID_ENV={env!r}. "
            "Expected one of: sandbox, development, production.",
            file=sys.stderr,
        )
        sys.exit(1)
    return base_url


def plaid_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = plaid_base_url().rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", "ignore")
        print(f"Plaid API error ({e.code}): {err_body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Network error calling Plaid API: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        print(f"Failed to parse Plaid response as JSON: {e}", file=sys.stderr)
        print(f"Raw response: {body}", file=sys.stderr)
        sys.exit(1)


def cmd_sandbox_link(args: argparse.Namespace) -> None:
    """Create a sandbox item, exchange its public_token for an access_token,
    and write it to a JSON file."""
    env = os.getenv("PLAID_ENV", "sandbox").lower()
    if env != "sandbox":
        print(
            "The 'sandbox-link' command only works with PLAID_ENV=sandbox.",
            file=sys.stderr,
        )
        sys.exit(1)

    client_id = getenv_or_die("PLAID_CLIENT_ID")
    secret = getenv_or_die("PLAID_SECRET")

    institution_id = args.institution_id
    output_path = args.output

    create_payload: Dict[str, Any] = {
        "client_id": client_id,
        "secret": secret,
        "institution_id": institution_id,
        "initial_products": ["transactions"],
    }
    create_resp = plaid_post("/sandbox/public_token/create", create_payload)
    public_token = create_resp.get("public_token")
    if not public_token:
        print(
            f"Unexpected response from /sandbox/public_token/create: {create_resp}",
            file=sys.stderr,
        )
        sys.exit(1)

    exchange_payload = {
        "client_id": client_id,
        "secret": secret,
        "public_token": public_token,
    }
    exchange_resp = plaid_post("/item/public_token/exchange", exchange_payload)
    access_token = exchange_resp.get("access_token")
    item_id = exchange_resp.get("item_id")

    if not access_token:
        print(
            f"Unexpected response from /item/public_token/exchange: {exchange_resp}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = {
        "access_token": access_token,
        "item_id": item_id,
        "created_at": dt.datetime.utcnow().isoformat() + "Z",
        "environment": env,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Wrote sandbox access token to {output_path}")
    print("Access token (copy this somewhere secure):")
    print(access_token)


def _parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def cmd_transactions(args: argparse.Namespace) -> None:
    """Fetch transactions for an existing access token and print them as JSON."""
    client_id = getenv_or_die("PLAID_CLIENT_ID")
    secret = getenv_or_die("PLAID_SECRET")

    access_token = args.access_token or os.getenv("PLAID_ACCESS_TOKEN")
    if not access_token:
        print(
            "Access token not provided. Use --access-token or set PLAID_ACCESS_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(1)

    today = dt.date.today()
    start_date = _parse_date(args.start_date) if args.start_date else today - dt.timedelta(days=30)
    end_date = _parse_date(args.end_date) if args.end_date else today

    payload: Dict[str, Any] = {
        "client_id": client_id,
        "secret": secret,
        "access_token": access_token,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "options": {
            "count": args.count,
            "offset": 0,
        },
    }

    resp = plaid_post("/transactions/get", payload)

    if args.raw:
        json.dump(resp, sys.stdout, indent=2)
        print()
        return

    transactions = resp.get("transactions", [])
    print(json.dumps(transactions, indent=2))
    print(f"\nTotal transactions returned: {len(transactions)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simple Plaid CLI: sandbox link + transactions fetch.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sandbox_parser = subparsers.add_parser(
        "sandbox-link",
        help="Create a sandbox item and write its access token to a JSON file.",
    )
    sandbox_parser.add_argument(
        "--institution-id",
        default="ins_109508",
        help="Sandbox institution ID (default: ins_109508 - Chase Sandbox)",
    )
    sandbox_parser.add_argument(
        "--output",
        default="plaid_access_token.json",
        help="File path to write access token JSON (default: plaid_access_token.json)",
    )
    sandbox_parser.set_defaults(func=cmd_sandbox_link)

    tx_parser = subparsers.add_parser(
        "transactions",
        help="Fetch transactions for an access token over a date range.",
    )
    tx_parser.add_argument(
        "--access-token",
        help="Plaid access token. If omitted, uses PLAID_ACCESS_TOKEN env var.",
    )
    tx_parser.add_argument(
        "--start-date",
        help="Start date (YYYY-MM-DD). Default: 30 days ago.",
    )
    tx_parser.add_argument(
        "--end-date",
        help="End date (YYYY-MM-DD). Default: today.",
    )
    tx_parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Max number of transactions to return (default: 100).",
    )
    tx_parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the full Plaid /transactions/get JSON response.",
    )
    tx_parser.set_defaults(func=cmd_transactions)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        sys.exit(1)
    func(args)


if __name__ == "__main__":
    main()
