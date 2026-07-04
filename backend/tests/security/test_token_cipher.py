from cryptography.fernet import Fernet
import pytest

from penny.security.token_cipher import decrypt_token, encrypt_token, is_encrypted


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("PENNY_PLAID_TOKEN_KEY", Fernet.generate_key().decode())


def test_round_trip():
    ct = encrypt_token("access-sandbox-123")
    assert ct != "access-sandbox-123"
    assert is_encrypted(ct)
    assert decrypt_token(ct) == "access-sandbox-123"


def test_ciphertext_carries_key_version_prefix():
    # The v<N>: stamp is what makes later key rotation a config change, not a
    # re-encrypt-everything migration.
    ct = encrypt_token("tok")
    assert ct.startswith("v1:")


def test_unprefixed_legacy_fernet_is_recognized_and_decrypts():
    import os

    key = Fernet(os.environ["PENNY_PLAID_TOKEN_KEY"].encode())
    legacy = key.encrypt(b"tok").decode()
    assert is_encrypted(legacy)  # gAAAAA sniff
    assert decrypt_token(legacy) == "tok"


def test_plaintext_is_not_encrypted():
    assert not is_encrypted("access-sandbox-123")


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("PENNY_PLAID_TOKEN_KEY", raising=False)
    with pytest.raises(RuntimeError):
        encrypt_token("tok")


def test_unknown_key_version_raises():
    with pytest.raises(ValueError):
        decrypt_token("v9:whatever")
