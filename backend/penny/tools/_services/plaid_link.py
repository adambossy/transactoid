"""Hosted Plaid Link: link-token creation + server-side public-token exchange.

Rearchitects the localhost Link flow (``connect_new_account``) for remote
deployment (productionization B-6): the ``react-plaid-link`` picker runs in the
browser and the ``public_token`` is exchanged **server-side** here. The localhost
flow stays for dev behind ``PENNY_PLAID_LINK_MODE=localhost``.

``create_link_token`` mints a token for the authenticated user;
``exchange_public_token`` exchanges it, encrypts the access token at rest, writes
the finance ``PlaidItem`` + ``PlaidAccount`` rows (owner/household from ``ctx``,
visibility ``private``), kicks off the first sync, and enqueues a ``plaid_link``
success reminder. All external collaborators (Plaid client, sync, reminder queue)
are injectable so tests drive the flow with fakes and no real Plaid.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
import threading
from typing import Any, Protocol
import uuid

from loguru import logger

from penny.adapters.clients.plaid import PlaidClient
from penny.adapters.db.models import PlaidAccount, PlaidItem
from penny.reminders import DbReminderQueue
from penny.security.token_cipher import encrypt_token_at_rest
from penny.tenancy.context import RequestContext


class _ReminderQueue(Protocol):
    async def enqueue(
        self, session_id: str, kind: str, content: str, *, override: bool = True
    ) -> None: ...


def _link_mode() -> str:
    return os.environ.get("PENNY_PLAID_LINK_MODE", "hosted").strip().lower() or "hosted"


def create_link_token(
    *, user_id: uuid.UUID, client: PlaidClient | None = None
) -> dict[str, Any]:
    """Create a Plaid ``link_token`` for ``user_id`` (hosted mode).

    Hosted mode (default) returns ``{mode: 'hosted', link_token, expiration}`` for
    the inline card. Localhost mode returns a pointer to the dev
    ``connect_new_account`` flow instead — no token is minted.
    """
    if _link_mode() == "localhost":
        return {
            "mode": "localhost",
            "instructions": (
                "Local dev uses the localhost Plaid Link flow — call "
                "connect_new_account to open the browser picker."
            ),
        }
    client = client or PlaidClient.from_env()
    redirect_uri = os.environ.get("PLAID_REDIRECT_URI", "").strip() or None
    link_token = client.create_link_token(
        user_id=str(user_id),
        redirect_uri=redirect_uri,
        products=["transactions"],
    )
    return {"mode": "hosted", "link_token": link_token, "expiration": None}


async def exchange_public_token(
    session: Any,
    ctx: RequestContext,
    *,
    public_token: str,
    conversation_id: str,
    client: Any = None,
    sync: Callable[[str], None] | None = None,
    queue: _ReminderQueue | None = None,
) -> dict[str, Any]:
    """Exchange a ``public_token`` and persist the linked item + accounts.

    Encrypts the access token at rest, inserts the ``PlaidItem`` and its
    ``PlaidAccount`` rows (owner = ``ctx.user``, visibility ``private``), fires
    the first sync (fire-and-forget), and enqueues a ``plaid_link`` reminder so
    the next turn relays the success. Returns ``{item_id, accounts}``.
    """
    client = client or PlaidClient.from_env()
    exch = await asyncio.to_thread(client.item_public_token_exchange, public_token)
    access_token = exch["access_token"]
    item_id = exch["item_id"]

    accounts_resp = await asyncio.to_thread(client.accounts_get, access_token)
    accounts = accounts_resp.get("accounts") or []
    institution = (accounts_resp.get("item") or {}).get(
        "institution_name"
    ) or "Your bank"

    # At-rest encryption, mirroring the facade's rule: dev without a key stores
    # plaintext, but clerk (prod) mode fails closed if the key is missing rather
    # than silently persisting a bank access token in cleartext (F07).
    stored_token = encrypt_token_at_rest(access_token)
    session.add(
        PlaidItem(
            item_id=item_id,
            access_token=stored_token,
            institution_name=institution,
            household_id=ctx.household_id,
            owner_user_id=ctx.user_id,
        )
    )
    # Flush the item before its accounts so the FK (accounts.item_id →
    # plaid_items) resolves under SQLite's enforced foreign keys.
    session.flush()
    for account in accounts:
        session.add(
            PlaidAccount(
                account_id=account["account_id"],
                item_id=item_id,
                owner_user_id=ctx.user_id,
                household_id=ctx.household_id,
                visibility="private",
                name=account.get("name"),
            )
        )
    session.flush()

    # First sync: fire-and-forget so the exchange returns immediately.
    (sync or _default_sync(ctx))(item_id)

    reminder_queue = queue or DbReminderQueue(ctx)
    content = (
        f"{institution} linked ({len(accounts)} accounts; first sync started). "
        "Tell the user, and mention they can connect more accounts anytime just "
        "by asking."
    )
    await reminder_queue.enqueue(conversation_id, "plaid_link", content)
    return {"item_id": item_id, "accounts": len(accounts)}


def _default_sync(ctx: RequestContext) -> Callable[[str], None]:
    """Return a fire-and-forget first-sync callable bound to ``ctx``.

    Runs the existing sync service in a daemon thread (its own event loop +
    request context) so a linked item pulls transactions without blocking the
    exchange response. Best-effort: failures are logged, never raised.
    """

    def _kick(item_id: str) -> None:
        def _run() -> None:
            from penny.db import get_db
            from penny.services import build_categorizer, get_taxonomy
            from penny.tenancy.context import set_request_context
            from penny.tools._services.sync_service import SyncTool

            set_request_context(ctx)
            try:
                tool = SyncTool(
                    plaid_client=PlaidClient.from_env(),
                    categorizer_factory=build_categorizer,
                    db=get_db(),
                    taxonomy=get_taxonomy(),
                )
                asyncio.run(tool.sync())
            except Exception:
                logger.exception("first sync after link failed for item {}", item_id)

        threading.Thread(target=_run, daemon=True).start()

    return _kick
