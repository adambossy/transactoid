from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date
from typing import Any, Dict, List, Literal, Optional, TypedDict

from models.transaction import Transaction
from pydantic import BaseModel, Field

PlaidEnv = Literal["sandbox", "development", "production"]


class PlaidClientError(Exception):
    """Base error for Plaid client failures."""


PLAID_ENV_MAP: Dict[PlaidEnv, str] = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidAccount(TypedDict):
    account_id: str
    name: str
    official_name: Optional[str]
    mask: Optional[str]
    subtype: Optional[str]
    type: Optional[str]
    institution: Optional[str]


class PlaidItemInfo(TypedDict):
    item_id: str
    institution_id: Optional[str]
    institution_name: Optional[str]


class PlaidBaseModel(BaseModel):
    """Shared base for Plaid response models with a short parse alias."""

    @classmethod
    def parse(cls, data: Any) -> "PlaidBaseModel":
        return cls.model_validate(data)


class LinkTokenCreateResponse(PlaidBaseModel):
    link_token: str


class AccountsGetAccount(PlaidBaseModel):
    account_id: str
    name: str
    official_name: Optional[str] = None
    mask: Optional[str] = None
    subtype: Optional[str] = None
    type: Optional[str] = None

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
    accounts: List[AccountsGetAccount]


class ItemModel(PlaidBaseModel):
    item_id: str
    institution_id: Optional[str] = None


class ItemGetResponse(PlaidBaseModel):
    item: ItemModel


class InstitutionModel(PlaidBaseModel):
    name: Optional[str] = None


class InstitutionGetByIdResponse(PlaidBaseModel):
    institution: Optional[InstitutionModel] = None


class PlaidTransactionModel(PlaidBaseModel):
    transaction_id: Optional[str] = None
    account_id: str
    amount: float
    iso_currency_code: Optional[str] = None
    date: str
    name: str
    merchant_name: Optional[str] = None
    pending: bool = False
    payment_channel: Optional[str] = None
    unofficial_currency_code: Optional[str] = None
    category: Optional[List[str]] = None
    category_id: Optional[str] = None
    personal_finance_category: Optional[Dict[str, Any]] = None

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
            "personal_finance_category": self.personal_finance_category,
        }
        return txn


class TransactionsGetResponse(PlaidBaseModel):
    transactions: List[PlaidTransactionModel] = Field(default_factory=list)


class TransactionsSyncResponse(PlaidBaseModel):
    added: List[PlaidTransactionModel] = Field(default_factory=list)
    modified: List[PlaidTransactionModel] = Field(default_factory=list)
    removed: List[Dict[str, Any]] = Field(default_factory=list)
    next_cursor: Optional[str] = None

    def to_sync_result(self, *, fallback_cursor: Optional[str]) -> Dict[str, Any]:
        return {
            "added": [txn.to_typed() for txn in self.added],
            "modified": [txn.to_typed() for txn in self.modified],
            "removed": self.removed,
            "next_cursor": self.next_cursor or (fallback_cursor or ""),
        }


class PlaidClient:
    def __init__(
        self,
        *,
        client_id: str,
        secret: str,
        env: PlaidEnv = "sandbox",
        client_name: str = "transactoid",
        products: Optional[List[str]] = None,
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
    def from_env(cls) -> "PlaidClient":
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

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self._base_url().rstrip("/") + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
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

        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise PlaidClientError(
                f"Failed to parse Plaid response as JSON: {e}: {body}"
            ) from e

    # High-level APIs -----------------------------------------------------

    def create_link_token(
        self,
        *,
        user_id: str,
        redirect_uri: Optional[str] = None,
        products: Optional[List[str]] = None,
        country_codes: Optional[List[str]] = None,
        language: str = "en",
        client_name: Optional[str] = None,
    ) -> str:
        """Create a Plaid Link token and return it."""
        payload: Dict[str, Any] = {
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

    def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
        """Call /transactions/get and return the raw Plaid response."""
        payload: Dict[str, Any] = {
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

    def get_accounts(self, access_token: str) -> List[PlaidAccount]:
        """Return accounts for an item using Plaid's /accounts/get endpoint."""
        payload: Dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
        }
        resp = AccountsGetResponse.parse(self._post("/accounts/get", payload))
        return [account.to_typed() for account in resp.accounts]

    def get_item_info(self, access_token: str) -> PlaidItemInfo:
        """Return item and institution information for an access token."""
        payload: Dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
        }
        item_resp = ItemGetResponse.parse(self._post("/item/get", payload))

        item_id = item_resp.item.item_id
        institution_id = item_resp.item.institution_id
        institution_name: Optional[str] = None

        if institution_id:
            inst_payload: Dict[str, Any] = {
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
        account_ids: Optional[List[str]] = None,
        offset: int = 0,
        limit: int = 500,
    ) -> List[Transaction]:
        """Return a page of transactions using Plaid's /transactions/get."""
        options: Dict[str, Any] = {
            "count": limit,
            "offset": offset,
        }
        if account_ids:
            options["account_ids"] = account_ids

        payload: Dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "options": options,
        }

        resp = TransactionsGetResponse.parse(
            self._post("/transactions/get", payload)
        )
        return [txn.to_typed() for txn in resp.transactions]

    def sync_transactions(
        self,
        access_token: str,
        *,
        cursor: Optional[str] = None,
        count: int = 500,
    ) -> Dict[str, Any]:
        """Thin wrapper around Plaid's /transactions/sync endpoint."""
        payload: Dict[str, Any] = {
            "client_id": self._client_id,
            "secret": self._secret,
            "access_token": access_token,
            "count": count,
        }
        if cursor is not None:
            payload["cursor"] = cursor

        resp = TransactionsSyncResponse.parse(
            self._post("/transactions/sync", payload)
        )
        return resp.to_sync_result(fallback_cursor=cursor)

    def institution_name_for_item(self, access_token: str) -> Optional[str]:
        """Convenience helper that returns only the institution name for an item."""
        info = self.get_item_info(access_token)
        return info.get("institution_name")
