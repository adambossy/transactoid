from __future__ import annotations

from collections.abc import Mapping
import os
import uuid

from penny.tenancy.context import RequestContext, SessionMode


def _lower_keys(headers: Mapping[str, str]) -> dict[str, str]:
    return {k.lower(): v for k, v in headers.items()}


def _pick(headers: dict[str, str], header_name: str, env_name: str) -> str | None:
    value = headers.get(header_name)
    if value:
        return value
    env_value = os.environ.get(env_name, "").strip()
    return env_value or None


def resolve_dev_principal(headers: Mapping[str, str]) -> RequestContext:
    """Dev-only principal: header overrides env. Replaced by real auth in phase 2."""
    h = _lower_keys(headers)
    user_raw = _pick(h, "x-penny-user-id", "PENNY_DEV_USER_ID")
    household_raw = _pick(h, "x-penny-household-id", "PENNY_DEV_HOUSEHOLD_ID")
    if not user_raw or not household_raw:
        raise ValueError(
            "Dev principal unconfigured: set X-Penny-User-Id/X-Penny-Household-Id "
            "headers or PENNY_DEV_USER_ID/PENNY_DEV_HOUSEHOLD_ID env vars"
        )
    mode_raw = (
        _pick(h, "x-penny-session-mode", "PENNY_DEV_SESSION_MODE") or "individual"
    )
    return RequestContext(
        user_id=uuid.UUID(user_raw),
        household_id=uuid.UUID(household_raw),
        session_mode=SessionMode(mode_raw),
    )
