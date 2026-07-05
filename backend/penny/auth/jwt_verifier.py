"""Clerk JWT verification (RS256, config-pinned issuer + JWKS).

The verifier trusts *config*, never the token: the JWKS URL comes from
``AuthSettings.jwks_url`` (not the token's ``iss``, which would be an SSRF
vector), ``iss``/``aud`` are checked against config, only ``RS256`` is accepted
(``alg=none``/alg-confusion rejected), and ``exp`` is enforced with 60s leeway.
Any PyJWT failure collapses to a uniform ``TokenError`` (→ HTTP 401), so the
caller never has to branch on the specific reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import jwt

from penny.auth.settings import AuthSettings


class TokenError(Exception):
    """The bearer token failed verification (maps to HTTP 401)."""


class ClerkJwtVerifier:
    def __init__(
        self,
        settings: AuthSettings,
        *,
        signing_key_for: Callable[[str], Any] | None = None,
    ) -> None:
        self._settings = settings
        if signing_key_for is None:
            # JWKS URL from config — never derived from the token's iss claim.
            client = jwt.PyJWKClient(settings.jwks_url, cache_keys=True)
            signing_key_for = lambda tok: client.get_signing_key_from_jwt(tok).key  # noqa: E731
        self._signing_key_for = signing_key_for

    def verify(self, token: str) -> dict:
        try:
            key = self._signing_key_for(token)
            return jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._settings.issuer,
                audience=self._settings.audience,
                leeway=60,
                options={"verify_aud": self._settings.audience is not None},
            )
        except Exception as exc:  # any PyJWT error → uniform 401
            raise TokenError(str(exc)) from exc
