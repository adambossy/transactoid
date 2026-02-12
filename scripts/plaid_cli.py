#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import queue
import sys
import threading
from typing import Any
import urllib.parse
import uuid
import webbrowser

from dotenv import load_dotenv

from transactoid.adapters.clients.plaid import PlaidClient, PlaidClientError
from transactoid.adapters.clients.plaid_link import (
    PublicTokenTimeoutError,
    RedirectServerError,
    shutdown_redirect_server,
    start_redirect_server,
    wait_for_public_token,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def plaid_create_link_token(
    *,
    user_id: str,
    redirect_uri: str,
    products: list[str],
    required_if_supported_products: list[str] | None = None,
    additional_consented_products: list[str] | None = None,
    access_token: str | None = None,
    client_name: str = "transactoid",
    language: str = "en",
    country_codes: list[str] | None = None,
) -> str:
    """Create a Plaid Link token and return it using the shared PlaidClient."""
    client = PlaidClient.from_env()
    try:
        return client.create_link_token(
            user_id=user_id,
            redirect_uri=redirect_uri,
            products=products,
            required_if_supported_products=required_if_supported_products,
            additional_consented_products=additional_consented_products,
            access_token=access_token,
            client_name=client_name,
            language=language,
            country_codes=country_codes,
        )
    except PlaidClientError as e:
        print(str(e), file=sys.stderr)
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

    try:
        client = PlaidClient.from_env()
    except PlaidClientError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    institution_id = args.institution_id
    output_path = args.output

    create_payload: dict[str, Any] = {
        "client_id": client._client_id,
        "secret": client._secret,
        "institution_id": institution_id,
        "initial_products": ["transactions"],
    }
    create_resp = client._post("/sandbox/public_token/create", create_payload)
    public_token = create_resp.get("public_token")
    if not public_token:
        print(
            f"Unexpected response from /sandbox/public_token/create: {create_resp}",
            file=sys.stderr,
        )
        sys.exit(1)

    exchange_resp = client.exchange_public_token(public_token)
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


def cmd_exchange_public_token(args: argparse.Namespace) -> None:
    """Exchange a Plaid Link public_token for an access_token."""
    public_token = args.public_token
    try:
        client = PlaidClient.from_env()
        resp = client.exchange_public_token(public_token)
    except PlaidClientError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    access_token = resp.get("access_token")
    item_id = resp.get("item_id")
    if not access_token:
        print(
            f"Unexpected response from /item/public_token/exchange: {resp}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = {
        "access_token": access_token,
        "item_id": item_id,
        "environment": os.getenv("PLAID_ENV", "sandbox").lower(),
        "created_at": dt.datetime.utcnow().isoformat() + "Z",
        "request_id": resp.get("request_id"),
        "expiration": resp.get("expiration"),
        "scope": resp.get("scope"),
    }

    output_path = args.output
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote access token details to {output_path}")

    print("Access token (copy this somewhere secure):")
    print(access_token)


def _parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def cmd_transactions(args: argparse.Namespace) -> None:
    """Fetch transactions for an existing access token and print them as JSON."""
    access_token = args.access_token or os.getenv("PLAID_ACCESS_TOKEN")
    if not access_token:
        print(
            "Access token not provided. Use --access-token or set PLAID_ACCESS_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(1)

    today = dt.date.today()
    start_date = (
        _parse_date(args.start_date)
        if args.start_date
        else today - dt.timedelta(days=30)
    )
    end_date = _parse_date(args.end_date) if args.end_date else today

    try:
        client = PlaidClient.from_env()
        resp = client.get_transactions_raw(
            access_token,
            start_date=start_date,
            end_date=end_date,
            count=args.count,
        )
    except PlaidClientError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    if args.raw:
        json.dump(resp, sys.stdout, indent=2)
        print()
        return

    transactions = resp.get("transactions", [])
    print(json.dumps(transactions, indent=2))
    print(f"\nTotal transactions returned: {len(transactions)}")


def _ensure_production_env() -> str:
    """Ensure PLAID_ENV is set and return its value (lowercased).

    This helper is business logic only; it does not print or exit.
    """
    env = os.getenv("PLAID_ENV")
    if env is None:
        env = "production"
        os.environ["PLAID_ENV"] = env
    env = env.lower()
    return env


def _create_redirect_server_and_uri(
    args: argparse.Namespace,
    *,
    redirect_path: str,
    token_queue: queue.Queue[str],
    state: dict[str, Any],
) -> tuple[Any, threading.Thread, str]:
    """Start the local HTTPS redirect server and return its URI."""
    try:
        server, server_thread, bound_host, bound_port = start_redirect_server(
            host=args.host,
            port=args.port,
            path=redirect_path,
            token_queue=token_queue,
            state=state,
        )
    except OSError as e:
        raise RedirectServerError(
            f"Failed to start the local redirect server on {args.host}:{args.port}: {e}"
        ) from e

    redirect_host = args.host or bound_host
    try:
        host_is_unspecified = ipaddress.ip_address(redirect_host).is_unspecified
    except ValueError:
        host_is_unspecified = redirect_host == ""
    if host_is_unspecified:
        redirect_host = "localhost"

    redirect_uri = f"https://{redirect_host}:{bound_port}{redirect_path}"
    return server, server_thread, redirect_uri


def _create_link_url(
    *,
    env: str,
    user_id: str,
    redirect_uri: str,
    products: list[str],
    country_codes: list[str],
    client_name: str,
    language: str,
    state: dict[str, Any],
    required_if_supported_products: list[str] | None = None,
    additional_consented_products: list[str] | None = None,
    access_token: str | None = None,
) -> str:
    """Create a Link token and return the hosted Link URL."""
    link_token = plaid_create_link_token(
        user_id=user_id,
        redirect_uri=redirect_uri,
        products=products,
        required_if_supported_products=required_if_supported_products,
        additional_consented_products=additional_consented_products,
        access_token=access_token,
        client_name=client_name,
        language=language,
        country_codes=country_codes,
    )
    state["link_token"] = link_token

    return "https://cdn.plaid.com/link/v2/stable/link.html?token=" + urllib.parse.quote(
        link_token, safe=""
    )


def _open_link_in_browser(link_url: str) -> bool:
    """Open the Plaid Link URL in the user's browser."""
    return webbrowser.open(link_url, new=1)


def _emit_public_token_result(
    *,
    public_token: str,
    env: str,
    output_path: str | None,
) -> None:
    result = {
        "public_token": public_token,
        "environment": env,
        "received_at": dt.datetime.utcnow().isoformat() + "Z",
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"Wrote public token details to {output_path}")

    print("Plaid public_token received. You can now exchange it for an access token:")
    print("  scripts/plaid_cli.py exchange-public-token <public_token>")
    print("\nPublic token (copy securely):")
    print(public_token)


def cmd_link_production(args: argparse.Namespace) -> None:
    """Drive a production Plaid Link flow via the hosted web experience."""
    env = _ensure_production_env()

    redirect_path = "/plaid-link-complete"
    token_queue: queue.Queue[str] = queue.Queue()
    state: dict[str, Any] = {}

    server, server_thread, redirect_uri = _create_redirect_server_and_uri(
        args,
        redirect_path=redirect_path,
        token_queue=token_queue,
        state=state,
    )

    user_id = args.user_id or f"cli-user-{uuid.uuid4()}"
    products = args.products or ["transactions"]
    country_codes = args.country_codes or ["US"]

    try:
        link_url = _create_link_url(
            env=env,
            user_id=user_id,
            redirect_uri=redirect_uri,
            products=products,
            country_codes=country_codes,
            client_name=args.client_name,
            language=args.language,
            state=state,
        )

        print(f"Listening for Plaid redirect on {redirect_uri}")
        print(
            "Your browser may warn about a self-signed certificate; "
            "bypass it once to continue."
        )
        print("Opening Plaid Link in your default browser...")
        opened = _open_link_in_browser(link_url)
        if not opened:
            print(
                "Unable to automatically open the browser. "
                "Open the following URL manually:",
                file=sys.stderr,
            )
            print(link_url)

        print(
            f"Waiting for Plaid Link to complete. Timeout: {args.timeout} seconds.",
        )
        public_token = wait_for_public_token(
            token_queue,
            timeout_seconds=args.timeout,
        )
    except RedirectServerError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except PublicTokenTimeoutError as e:
        print(str(e), file=sys.stderr)
        print("Restart the command to try again.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted before Plaid Link completed.", file=sys.stderr)
        sys.exit(1)
    finally:
        shutdown_redirect_server(server, server_thread)

    _emit_public_token_result(
        public_token=public_token,
        env=env,
        output_path=args.output,
    )


def cmd_add_investments_consent(args: argparse.Namespace) -> None:
    """Add investments consent to an existing Plaid item via update-mode Link."""
    env = _ensure_production_env()

    # Get access token from arg or DB
    access_token = args.access_token
    if not access_token:
        if not args.item_id:
            print(
                "Error: Must provide either --access-token or --item-id",
                file=sys.stderr,
            )
            sys.exit(1)

        # Load access token from database
        try:
            from transactoid.adapters.db.facade import DB

            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                print(
                    "Error: DATABASE_URL not set. Cannot load item from database.",
                    file=sys.stderr,
                )
                sys.exit(1)

            db = DB(db_url)
            item = db.get_plaid_item(args.item_id)
            if not item:
                print(
                    f"Error: Item {args.item_id} not found in database.",
                    file=sys.stderr,
                )
                sys.exit(1)
            access_token = item.access_token
            print(f"Loaded access token for item {args.item_id}")
        except Exception as e:
            print(f"Error loading item from database: {e}", file=sys.stderr)
            sys.exit(1)

    redirect_path = "/plaid-link-complete"
    token_queue: queue.Queue[str] = queue.Queue()
    state: dict[str, Any] = {}

    server, server_thread, redirect_uri = _create_redirect_server_and_uri(
        args,
        redirect_path=redirect_path,
        token_queue=token_queue,
        state=state,
    )

    user_id = f"cli-user-{uuid.uuid4()}"

    try:
        # Create update-mode link token with access_token and investments
        link_url = _create_link_url(
            env=env,
            user_id=user_id,
            redirect_uri=redirect_uri,
            products=["transactions"],
            additional_consented_products=["investments"],
            access_token=access_token,
            country_codes=["US"],
            client_name=args.client_name,
            language=args.language,
            state=state,
        )

        print(f"Listening for Plaid redirect on {redirect_uri}")
        print("Adding investments consent to existing item...")
        print(
            "Your browser may warn about a self-signed certificate; "
            "bypass it once to continue."
        )
        print("Opening Plaid Link in your default browser...")
        opened = _open_link_in_browser(link_url)
        if not opened:
            print(
                "Unable to automatically open the browser. "
                "Open the following URL manually:",
                file=sys.stderr,
            )
            print(link_url)

        print(
            f"Waiting for Plaid Link to complete. Timeout: {args.timeout} seconds.",
        )
        public_token = wait_for_public_token(
            token_queue,
            timeout_seconds=args.timeout,
        )
    except RedirectServerError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except PublicTokenTimeoutError as e:
        print(str(e), file=sys.stderr)
        print("Restart the command to try again.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted before Plaid Link completed.", file=sys.stderr)
        sys.exit(1)
    finally:
        shutdown_redirect_server(server, server_thread)

    print(f"✓ Received public_token: {public_token[:20]}...")
    print("Investments consent added successfully!")
    print(
        "Note: If the item_id changed, you may need to migrate the item identity "
        "in your database."
    )


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

    exchange_parser = subparsers.add_parser(
        "exchange-public-token",
        help="Exchange a Plaid Link public token for an access token.",
    )
    exchange_parser.add_argument(
        "public_token",
        help="public_token returned by Plaid Link",
    )
    exchange_parser.add_argument(
        "--output",
        help="Optional file path to write the resulting access token as JSON.",
    )
    exchange_parser.set_defaults(func=cmd_exchange_public_token)

    prod_link_parser = subparsers.add_parser(
        "link-production",
        help=(
            "Launch Plaid Link in production using the hosted web flow and capture the "
            "public_token via a browser redirect."
        ),
    )
    prod_link_parser.add_argument(
        "--user-id",
        help="Value for Plaid client_user_id. Defaults to a random UUID.",
    )
    prod_link_parser.add_argument(
        "--client-name",
        default="transactoid",
        help="Label shown inside Plaid Link (default: transactoid).",
    )
    prod_link_parser.add_argument(
        "--language",
        default="en",
        help="Plaid Link language code (default: en).",
    )
    prod_link_parser.add_argument(
        "--product",
        dest="products",
        action="append",
        help=(
            "Plaid product to request (e.g., transactions). "
            "Repeat to request multiple products. Default: transactions."
        ),
    )
    prod_link_parser.add_argument(
        "--country-code",
        dest="country_codes",
        action="append",
        help="Country code to include (default: US). Repeat for multiple countries.",
    )
    prod_link_parser.add_argument(
        "--host",
        default="localhost",
        help=(
            "Host interface for the local HTTPS redirect server (default: localhost). "
            "Must match a redirect URI registered in Plaid."
        ),
    )
    prod_link_parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help=(
            "Port for the redirect server (default: 8443). "
            "Use 0 to choose a random open port."
        ),
    )
    prod_link_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for Plaid Link to complete (default: 300).",
    )
    prod_link_parser.add_argument(
        "--output",
        help="Optional path to save the received public_token JSON payload.",
    )
    prod_link_parser.set_defaults(func=cmd_link_production)

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

    consent_parser = subparsers.add_parser(
        "add-investments-consent",
        help="Add investments consent to an existing Plaid item.",
    )
    consent_parser.add_argument(
        "--access-token",
        help="Plaid access token for the item. Alternative to --item-id.",
    )
    consent_parser.add_argument(
        "--item-id",
        help="Plaid item ID to load from database. Alternative to --access-token.",
    )
    consent_parser.add_argument(
        "--client-name",
        default="transactoid",
        help="Label shown inside Plaid Link (default: transactoid).",
    )
    consent_parser.add_argument(
        "--language",
        default="en",
        help="Plaid Link language code (default: en).",
    )
    consent_parser.add_argument(
        "--host",
        default="localhost",
        help=(
            "Host interface for the local HTTPS redirect server (default: localhost). "
            "Must match a redirect URI registered in Plaid."
        ),
    )
    consent_parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help=(
            "Port for the redirect server (default: 8443). "
            "Use 0 to choose a random open port."
        ),
    )
    consent_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for Plaid Link to complete (default: 300).",
    )
    consent_parser.set_defaults(func=cmd_add_investments_consent)

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
