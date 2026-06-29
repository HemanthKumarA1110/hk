import pytest
from trading_shared.security.encryption import decrypt_value, encrypt_value
from trading_shared.security.jwt_handler import create_access_token, decode_token
from trading_shared.security.password import hash_password, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("StrongPass123!")
    assert verify_password("StrongPass123!", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_access_token():
    token = create_access_token("42", {"role": "admin"})
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"
    assert payload["role"] == "admin"


def test_encryption_roundtrip():
    key = "phase1_dev_encryption_key_32chars"
    encrypted = encrypt_value("secret-api-key", key)
    assert decrypt_value(encrypted, key) == "secret-api-key"
