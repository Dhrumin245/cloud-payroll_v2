"""bcrypt password hashing.

Uses the `bcrypt` library directly (passlib is unmaintained and breaks with bcrypt 5).
Hashes are standard `$2b$...` strings, so hashes created by the legacy passlib-based
monolith still verify here.
"""

from functools import lru_cache

import bcrypt

from app.config import get_settings

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt ignores everything after 72 bytes


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # malformed hash or >72-byte password
        return False


@lru_cache
def _dummy_hash() -> str:
    return hash_password("dummy-password-used-only-for-timing")


def burn_time(password: str) -> None:
    """Do a hash check anyway for unknown users, so response time doesn't reveal them."""
    verify_password(password, _dummy_hash())
