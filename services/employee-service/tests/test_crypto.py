import pytest
from cryptography.fernet import Fernet

from app import crypto


def test_roundtrip_and_ciphertext_differs():
    token = crypto.encrypt("123456789012")
    assert token != "123456789012" and crypto.decrypt(token) == "123456789012"


def test_same_plaintext_encrypts_differently():
    assert crypto.encrypt("123456789012") != crypto.encrypt("123456789012")


def test_wrong_key_or_tampering_raises_value_error():
    foreign = Fernet(Fernet.generate_key()).encrypt(b"123456789012").decode()
    with pytest.raises(ValueError):
        crypto.decrypt(foreign)
    with pytest.raises(ValueError):
        crypto.decrypt("garbage")


def test_last4():
    assert crypto.last4("123456789012") == "9012"
