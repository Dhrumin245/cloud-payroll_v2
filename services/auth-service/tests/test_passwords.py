from app.passwords import hash_password, verify_password


def test_hash_and_verify():
    h = hash_password("a-good-password")
    assert h.startswith("$2b$")  # same format the legacy passlib hashes used
    assert verify_password("a-good-password", h)
    assert not verify_password("wrong", h)


def test_hashes_are_salted():
    assert hash_password("same-password") != hash_password("same-password")


def test_overlong_password_does_not_raise():
    h = hash_password("x" * 20)
    assert verify_password("y" * 100, h) is False


def test_malformed_hash_is_false():
    assert verify_password("anything", "not-a-bcrypt-hash") is False
