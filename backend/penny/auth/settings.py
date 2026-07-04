"""Fail-closed auth settings.

``load_auth_settings`` reads the ``PENNY_*`` auth env contract and refuses to
start in an insecure shape: ``clerk`` is the default mode, and clerk mode
*requires* the issuer, the JWKS URL, and the frontend origin (for CORS). Only
``clerk`` and ``dev`` are valid modes; anything else raises. This is the config
seam the FastAPI dependency and startup validation consume.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class AuthSettings:
    mode: str  # "clerk" | "dev"
    issuer: str | None
    jwks_url: str | None
    audience: str | None
    frontend_origin: str | None


def load_auth_settings() -> AuthSettings:
    mode = os.environ.get("PENNY_AUTH_MODE", "").strip() or "clerk"
    if mode not in ("clerk", "dev"):
        raise RuntimeError(f"PENNY_AUTH_MODE must be 'clerk' or 'dev', got {mode!r}")
    issuer = os.environ.get("PENNY_CLERK_ISSUER", "").strip() or None
    jwks_url = os.environ.get("PENNY_CLERK_JWKS_URL", "").strip() or None
    audience = os.environ.get("PENNY_CLERK_AUDIENCE", "").strip() or None
    origin = os.environ.get("PENNY_FRONTEND_ORIGIN", "").strip() or None
    if mode == "clerk":
        missing = [
            name
            for name, val in [
                ("PENNY_CLERK_ISSUER", issuer),
                ("PENNY_CLERK_JWKS_URL", jwks_url),
                ("PENNY_FRONTEND_ORIGIN", origin),
            ]
            if val is None
        ]
        if missing:
            raise RuntimeError(f"clerk auth mode requires: {', '.join(missing)}")
    return AuthSettings(
        mode=mode,
        issuer=issuer,
        jwks_url=jwks_url,
        audience=audience,
        frontend_origin=origin,
    )
