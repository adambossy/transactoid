"""Fernet encryption for Plaid access tokens at rest.

Stored ciphertext is stamped with a key version — ``v1:<fernet-token>`` — so
key rotation later means adding a key and bumping the active version, not a
re-encrypt-everything migration. ``decrypt_token`` selects the key by prefix
(bare ``gAAAAA…`` Fernet values from before the stamp decrypt with v1).

The token is decrypted only at the Plaid call site; it must never appear in
logs or prompts.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

# The active key version written by encrypt_token. Rotation: introduce
# PENNY_PLAID_TOKEN_KEY_V<N>, bump this, keep old keys readable.
_ACTIVE_VERSION = 1

# Fernet tokens are base64 starting with 0x80 0x00.. — always "gAAAAA".
_FERNET_SNIFF = "gAAAAA"


def _key_for_version(version: int) -> Fernet:
    if version != _ACTIVE_VERSION:
        raise ValueError(f"Unknown Plaid token key version v{version}")
    key = os.environ.get("PENNY_PLAID_TOKEN_KEY", "").strip()
    if not key:
        raise RuntimeError("PENNY_PLAID_TOKEN_KEY is not set")
    return Fernet(key.encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt with the active key, stamped ``v<N>:``."""
    ciphertext = _key_for_version(_ACTIVE_VERSION).encrypt(plaintext.encode()).decode()
    return f"v{_ACTIVE_VERSION}:{ciphertext}"


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stamped (or legacy unprefixed Fernet) token."""
    version, _, body = ciphertext.partition(":")
    if body and _is_version_tag(version):
        return _key_for_version(int(version[1:])).decrypt(body.encode()).decode()
    # Legacy: bare Fernet value written before the version stamp existed.
    return _key_for_version(_ACTIVE_VERSION).decrypt(ciphertext.encode()).decode()


def is_encrypted(value: str) -> bool:
    """True for stamped ciphertext or a legacy bare Fernet value.

    Keeps the write path and migration 017 idempotent: already-encrypted
    values are never double-encrypted.
    """
    version, _, body = value.partition(":")
    if body and _is_version_tag(version):
        return True
    return value.startswith(_FERNET_SNIFF)


def _is_version_tag(tag: str) -> bool:
    return len(tag) >= 2 and tag[0] == "v" and tag[1:].isdigit()
