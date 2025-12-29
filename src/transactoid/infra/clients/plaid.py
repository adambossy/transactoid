from __future__ import annotations

from collections.abc import Callable
from datetime import date
from http.server import ThreadingHTTPServer
import json
import os
import queue
import threading
from typing import Any, Literal, Self, TypedDict, cast
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, Field

from models.transaction import PersonalFinanceCategory, Transaction
from transactoid.infra.clients.plaid_link import (
    build_success_message,
    create_link_token_and_url,
    exchange_token_and_get_item_info,
    open_link_in_browser,
    save_item_to_database,
    setup_redirect_server,
    shutdown_redirect_server,
    wait_for_public_token_safe,
)

PlaidEnv = Literal["sandbox", "development", "production"]


class PlaidClientError(Exception):
    """Base error for Plaid client failures."""


PLAID_ENV_MAP: dict[PlaidEnv, str] = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidAccount(TypedDict):
    account_id: str
    name: str
    official_name: str | None
    mask: str | None
    subtype: str | None
    type: str | None
    institution: str | None


class PlaidItemInfo(TypedDict):
    item_id: str
    institution_id: str | None
    institution_name: str | None


class PlaidBaseModel(BaseModel):
    """Shared base for Plaid response models with a short parse alias."""

    @classmethod
    def parse(cls, data: Any) -> Self:
        return cls.model_validate(data)


class LinkTokenCreateResponse(PlaidBaseModel):
    link_token: str


class AccountsGetAccount(PlaidBaseModel):
    account_id: str
    name: str
    official_name: str | None = None
    mask: str | None = None
    subtype: str | None = None
    type: str | None = None

    def to_typed(self) -> PlaidAccount:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "official_name": self.official_name,
            "mask": self.mask,
            "subtype": self.subtype,
            "type": self.type,
            # Institution name can be resolved separately via get_item_info().
            "institution": None,
        }


class AccountsGetResponse(PlaidBaseModel):
    accounts: list[AccountsGetAccount]


class ItemModel(PlaidBaseModel):
    item_id: str
    institution_id: str | None = None


class ItemGetResponse(PlaidBaseModel):
    item: ItemModel


class InstitutionModel(PlaidBaseModel):
    name: str | None = None


class InstitutionGetByIdResponse(PlaidBaseModel):
    institution: InstitutionModel | None = None


class AccountWithInstitution(PlaidBaseModel):
    """Account information combined with institution and item details."""

    account_id: str
    name: str
    official_name: str | None = None
    mask: str | None = None
    subtype: str | None = None
    type: str | None = None
    institution_name: str | None = None
    institution_id: str | None = None
    item_id: str


class PlaidTransactionModel(PlaidBaseModel):
    transaction_id: str | None = None
    account_id: str
    amount: float
    iso_currency_code: str | None = None
    date: str
    name: str
    merchant_name: str | None = None
    pending: bool = False
    payment_channel: str | None = None
    unofficial_currency_code: str | None = None
    category: list[str] | None = None
    category_id: str | None = None
    personal_finance_category: dict[str, Any] | None = None

    def to_typed(self) -> Transaction:
        txn: Transaction = {
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "amount": self.amount,
            "iso_currency_code": self.iso_currency_code,
            "date": self.date,
            "name": self.name,
            "merchant_name": self.merchant_name,
            "pending": self.pending,
            "payment_channel": self.payment_channel,
            "unofficial_currency_code": self.unofficial_currency_code,
            "category": self.category,
            "category_id": self.category_id,
            "personal_finance_category": cast(
                PersonalFinanceCategory | None, self.personal_finance_category
            ),
        }
        return txn


class TransactionsGetResponse(PlaidBaseModel):
    transactions: list[PlaidTransactionModel] = Field(default_factory=list)


class TransactionsSyncResponse(PlaidBaseModel):
    added: list[PlaidTransactionModel] = Field(default_factory=list)
    modified: list[PlaidTransactionModel] = Field(default_factory=list)
    removed: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False

    def to_sync_result(self, *, fallback_cursor: str | None) -> dict[str, Any]:
        return {
            "added": [txn.to_typed() for txn in self.added],
            "modified": [txn.to_typed() for txn in self.modified],
            "removed": self.removed,
            "next_cursor": self.next_cursor or (fallback_cursor or ""),
            "has_more": self.has_more,
        }


class PlaidClient:
    def __init__(
        self,
        *,
        client_id: str,
        secret: str,
        env: PlaidEnv = "sandbox",
        client_name: str = "transactoid",
        products: list[str] | None = None,
    ) -> None:
        self._client_id = client_id
        self._secret = secret
        self._env = env
        self._client_name = client_name
        self._products = products or []

    @property
    def env(self) -> PlaidEnv:
        return self._env

    @classmethod
    def from_env(cls) -> PlaidClient:
        """Construct a PlaidClient from environment variables.

        Required:
        - PLAID_CLIENT_ID
        - PLAID_ENV (defaults to sandbox)
        - PLAID_<ENV>_SECRET (e.g. PLAID_SANDBOX_SECRET)
        """
        env_str = os.getenv("PLAID_ENV", "sandbox").lower()
        if env_str not in PLAID_ENV_MAP:
            raise PlaidClientError(
                f"Invalid PLAID_ENV={env_str!r}. "
                "Expected one of: sandbox, development, production."
            )
        env: PlaidEnv = env_str  # type: ignore[assignment]

        client_id = cls._getenv_or_die("PLAID_CLIENT_ID")
        secret = cls._secret_from_env(env)
        client_name = os.getenv("PLAID_CLIENT_NAME", "transactoid")
        return cls(client_id=client_id, secret=secret, env=env, client_name=client_name)

    @staticmethod
    def _getenv_or_die(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise PlaidClientError(f"Missing required environment variable: {name}")
        return value

    @classmethod
    def _secret_from_env(cls, env: PlaidEnv) -> str:
        if env == "production":
            return cls._getenv_or_die("PLAID_PRODUCTION_SECRET")
        if env == "development":
            return cls._getenv_or_die("PLAID_DEVELOPMENT_SECRET")
        if env == "sandbox":
            return cls._getenv_or_die("PLAID_SANDBOX_SECRET")
        raise PlaidClientError(f"Invalid PLAID_ENV={env!r}")

    def _base_url(self) -> str:
        try:
            return PLAID_ENV_MAP[self._env]
        except KeyError as e:
            raise PlaidClientError(
                f"Unsupported Plaid environment: {self._env!r}"
            ) from e

    def _parse_json_response(self, body: str) -> dict[str, Any]:
        """Parse JSON response from Plaid API.

        Args:
            body: JSON response body as string

        Returns:
            Parsed JSON as dictionary

        Raises:
            PlaidClientError: If JSON parsing fails
        """
        try:
            return cast(dict[str, Any], json.loads(body))
        except json.JSONDecodeError as e:
            raise PlaidClientError(
                f"Failed to parse Plaid response as JSON: {e}: {body}"
            ) from e

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._base_url().rstrip("/") + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310 - external HTTPS
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:  # pragma: no cover - network-dependent
            err_body = e.read().decode("utf-8", "ignore")
            raise PlaidClientError(f"Plaid API error ({e.code}): {err_body}") from e
        except urllib.error.URLError as e:  # pragma: no cover - network-dependent
            raise PlaidClientError(f"Network error calling Plaid API: {e}") from e

        return self._parse_json_response(body)

    # High-level APIs -----------------------------------------------------

    def create_link_token(
        self,
        *,
        user_id: str,
        redirect_uri: str | None = None,
        products: list[str] | None = None,
        country_codes: list[str] | None = None,
        language: str = "en",
        client_name: str | None = None,
    ) -> str:
        """Create a Plaid Link token and return it."""
        payload: dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "client_name": client_name or self._client_name,
            "language": language,
            "country_codes": country_codes or ["US"],
            "user": {"client_user_id": user_id},
            "products": products or self._products or [],
        }
        if redirect_uri is not None:
            payload["redirect_uri"] = redirect_uri

        resp = LinkTokenCreateResponse.parse(self._post("/link/token/create", payload))
        return resp.link_token

    def exchange_public_token(self, public_token: str) -> dict[str, Any]:
        """Exchange a Link public_token for an access_token."""
        payload = {
            "client_id": self._client_id,
            "secret": self._secret,
            "public_token": public_token,
        }
        return self._post("/item/public_token/exchange", payload)

    def get_transactions_raw(
        self,
        access_token: str,
        *,
        start_date: date,
        end_date: date,
        count: int = 100,
    ) -> dict[str, Any]:
        """Call /transactions/get and return the raw Plaid response."""
        payload: dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "options": {
                "count": count,
                "offset": 0,
            },
        }
        return self._post("/transactions/get", payload)

    def get_accounts(self, access_token: str) -> list[PlaidAccount]:
        """Return accounts for an item using Plaid's /accounts/get endpoint."""
        payload: dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
        }
        resp = AccountsGetResponse.parse(self._post("/accounts/get", payload))
        return [account.to_typed() for account in resp.accounts]

    def get_item_info(self, access_token: str) -> PlaidItemInfo:
        """Return item and institution information for an access token."""
        payload: dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
        }
        item_resp = ItemGetResponse.parse(self._post("/item/get", payload))

        item_id = item_resp.item.item_id
        institution_id = item_resp.item.institution_id
        institution_name: str | None = None

        if institution_id:
            inst_payload: dict[str, Any] = {
                "client_id": self._client_id,
                "secret": self._secret,
                "institution_id": institution_id,
                "country_codes": ["US"],
            }
            inst_resp = InstitutionGetByIdResponse.parse(
                self._post("/institutions/get_by_id", inst_payload)
            )
            if inst_resp.institution and inst_resp.institution.name:
                institution_name = inst_resp.institution.name

        info: PlaidItemInfo = {
            "item_id": item_id,
            "institution_id": institution_id,
            "institution_name": institution_name,
        }
        return info

    def list_transactions(
        self,
        access_token: str,
        *,
        start_date: date,
        end_date: date,
        account_ids: list[str] | None = None,
        offset: int = 0,
        limit: int = 500,
    ) -> list[Transaction]:
        """Return a page of transactions using Plaid's /transactions/get."""
        options: dict[str, Any] = {
            "count": limit,
            "offset": offset,
        }
        if account_ids:
            options["account_ids"] = account_ids

        payload: dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "options": options,
        }

        resp = TransactionsGetResponse.parse(self._post("/transactions/get", payload))
        return [txn.to_typed() for txn in resp.transactions]

    def sync_transactions(
        self,
        access_token: str,
        *,
        cursor: str | None = None,
        count: int = 500,
    ) -> dict[str, Any]:
        """Thin wrapper around Plaid's /transactions/sync endpoint."""
        payload: dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
            "count": count,
        }
        if cursor is not None:
            payload["cursor"] = cursor

        resp = TransactionsSyncResponse.parse(self._post("/transactions/sync", payload))
        return resp.to_sync_result(fallback_cursor=cursor)

    def institution_name_for_item(self, access_token: str) -> str | None:
        """Convenience helper that returns only the institution name for an item."""
        info = self.get_item_info(access_token)
        return info.get("institution_name")

    def connect_new_account(
        self,
        *,
        db: Any,  # DB type from services.db, avoiding circular import
        timeout_seconds: int = 300,
    ) -> dict[str, Any]:
        """Connect a new bank account via Plaid Link.

        Opens a browser window for the user to link their bank account via Plaid Link.
        The function handles the full OAuth flow, exchanges the public token for an
        access token, and stores the connection in the database.

        Args:
            db: Database instance with save_plaid_item method
            timeout_seconds: Timeout for waiting for Plaid Link completion
                (default: 300)

        Returns:
            Dictionary with connection status including:
            - status: "success" or "error"
            - item_id: Plaid item ID if successful
            - institution_name: Institution name if available
            - message: Human-readable status message
        """
        token_queue: queue.Queue[str] = queue.Queue()
        state: dict[str, Any] = {}
        server: ThreadingHTTPServer | None = None
        server_thread: threading.Thread | None = None

        # Set up redirect server
        server_result = setup_redirect_server(
            token_queue=token_queue,
            state=state,
        )
        if server_result is None:
            return {
                "status": "error",
                "message": "Failed to start redirect server",
            }
        server, server_thread, redirect_uri = server_result

        try:
            # Create Link token and URL
            link_url = create_link_token_and_url(
                redirect_uri=redirect_uri,
                state=state,
                create_link_token_fn=self.create_link_token,
                client_name=self._client_name,
            )

            # Open browser
            browser_error = open_link_in_browser(link_url)
            if browser_error:
                return browser_error

            # Wait for public token
            public_token = wait_for_public_token_safe(
                token_queue=token_queue,
                timeout_seconds=timeout_seconds,
            )
            if public_token is None:
                return {
                    "status": "error",
                    "message": (
                        "Timed out waiting for Plaid Link to complete. "
                        "Please try again."
                    ),
                }

            # Exchange token and get item info
            item_data = exchange_token_and_get_item_info(
                public_token=public_token,
                exchange_public_token_fn=self.exchange_public_token,
                get_item_info_fn=cast(
                    Callable[[str], dict[str, Any]], self.get_item_info
                ),
            )
            if item_data is None:
                return {
                    "status": "error",
                    "message": "Failed to exchange public token",
                }

            access_token = item_data["access_token"]
            item_id = item_data["item_id"]
            institution_name = item_data["institution_name"]
            institution_id = item_data["institution_id"]

            # Save to database
            db_error = save_item_to_database(
                db=db,
                item_id=item_id,
                access_token=access_token,
                institution_id=institution_id,
                institution_name=institution_name,
            )
            if db_error:
                return db_error

            return {
                "status": "success",
                "item_id": item_id,
                "institution_name": institution_name,
                "message": build_success_message(
                    item_id=item_id,
                    institution_name=institution_name,
                ),
            }

        except KeyboardInterrupt:
            return {
                "status": "error",
                "message": "Connection cancelled by user.",
            }
        finally:
            if server is not None and server_thread is not None:
                shutdown_redirect_server(server, server_thread)

    def list_accounts(
        self,
        *,
        db: Any,  # DB type from services.db, avoiding circular import
    ) -> dict[str, Any]:
        """List all connected bank accounts from Plaid items.

        Queries the database for all Plaid items and fetches account details
        from Plaid for each item.

        Args:
            db: Database instance with list_plaid_items method

        Returns:
            Dictionary with account listing status including:
            - status: "success" or "error"
            - accounts: List of account dictionaries, each containing:
              - Account details (account_id, name, official_name, mask, subtype, type)
              - Institution information (institution_name, institution_id, item_id)
            - message: Human-readable status message
        """
        plaid_items = db.list_plaid_items()
        if not plaid_items:
            return {
                "status": "success",
                "accounts": [],
                "message": "No connected accounts found.",
            }

        all_accounts: list[dict[str, Any]] = []
        errors: list[str] = []

        for item in plaid_items:
            try:
                accounts = self.get_accounts(item.access_token)
                item_info = self.get_item_info(item.access_token)

                for account in accounts:
                    account_data: dict[str, Any] = {
                        **account,
                        "institution_name": item_info.get("institution_name")
                        or item.institution_name,
                        "institution_id": item_info.get("institution_id")
                        or item.institution_id,
                        "item_id": item.item_id,
                    }
                    account_with_institution = AccountWithInstitution.parse(
                        account_data
                    )
                    all_accounts.append(account_with_institution.model_dump())
            except Exception as e:
                errors.append(
                    f"Failed to fetch accounts for item {item.item_id}: {str(e)}"
                )

        if errors and not all_accounts:
            return {
                "status": "error",
                "accounts": [],
                "message": f"Failed to fetch accounts: {'; '.join(errors)}",
            }

        message = (
            f"Found {len(all_accounts)} account(s) across "
            f"{len(plaid_items)} institution(s)."
        )
        if errors:
            message += (
                f" Note: {len(errors)} error(s) occurred while fetching some accounts."
            )

        return {
            "status": "success",
            "accounts": all_accounts,
            "message": message,
        }
