import time

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import pytest

from penny.auth.jwt_verifier import ClerkJwtVerifier, TokenError
from penny.auth.settings import AuthSettings

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SETTINGS = AuthSettings(
    mode="clerk",
    issuer="https://iss.example",
    jwks_url="https://iss.example/jwks",
    audience=None,
    frontend_origin="https://app.example",
)


def _make(claims: dict, key=KEY, alg="RS256") -> str:
    base = {
        "iss": "https://iss.example",
        "exp": int(time.time()) + 300,
        "sub": "user_1",
        "email": "a@x.com",
        "email_verified": True,
    }
    return jwt.encode({**base, **claims}, key, algorithm=alg)


def _verifier() -> ClerkJwtVerifier:
    return ClerkJwtVerifier(SETTINGS, signing_key_for=lambda tok: KEY.public_key())


def test_valid_token_returns_claims():
    claims = _verifier().verify(_make({}))
    assert claims["sub"] == "user_1"


def test_wrong_issuer_rejected():
    with pytest.raises(TokenError):
        _verifier().verify(_make({"iss": "https://evil.example"}))


def test_expired_rejected():
    with pytest.raises(TokenError):
        _verifier().verify(_make({"exp": int(time.time()) - 3600}))


def test_alg_none_rejected():
    header = jwt.encode({"sub": "user_1"}, None, algorithm="none")
    with pytest.raises(TokenError):
        _verifier().verify(header)


def test_garbage_rejected():
    with pytest.raises(TokenError):
        _verifier().verify("not-a-jwt")
