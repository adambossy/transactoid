from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional, TypedDict

from models.transaction import Transaction

PlaidEnv = Literal["sandbox", "development", "production"]


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

    def create_link_token(self, *, user_id: str, redirect_uri: Optional[str] = None) -> str:
        return "stub-link-token"

    def exchange_public_token(self, public_token: str) -> Dict[str, str]:
        return {"access_token": "stub-access-token", "item_id": "stub-item-id"}

    def get_accounts(self, access_token: str) -> List[PlaidAccount]:
        return []

    def get_item_info(self, access_token: str) -> PlaidItemInfo:
        return {"item_id": "stub-item", "institution_id": None, "institution_name": None}

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
        return []

    def sync_transactions(
        self,
        access_token: str,
        *,
        cursor: Optional[str] = None,
        count: int = 500,
    ) -> Dict[str, Any]:
        return {"added": [], "modified": [], "removed": [], "next_cursor": cursor or ""}

    def institution_name_for_item(self, access_token: str) -> Optional[str]:
        return None


